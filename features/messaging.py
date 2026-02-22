import os
import uuid
from datetime import datetime

from flask import Blueprint, render_template, request, session, jsonify
from werkzeug.utils import secure_filename
from flask_socketio import join_room, emit

from database import db_helper


# =========================
# Socket helpers / presence
# =========================

online_users = {}  # user_id -> sid

def dm_room(a: int, b: int) -> str:
    return f"dm_{min(a,b)}_{max(a,b)}"

def init_messaging(socketio):

    @socketio.on("presence_join")
    def presence_join(_data=None):
        if "user_id" not in session:
            return
        uid = int(session["user_id"])
        online_users[uid] = request.sid
        socketio.emit("online_list", list(online_users.keys()))

    @socketio.on("disconnect")
    def on_disconnect():
        dead = None
        for uid, sid in list(online_users.items()):
            if sid == request.sid:
                dead = uid
                break
        if dead is not None:
            online_users.pop(dead, None)
            socketio.emit("online_list", list(online_users.keys()))

    @socketio.on("dm_join")
    def dm_join(data):
        if "user_id" not in session:
            return

        me = int(session["user_id"])
        other = int((data or {}).get("other_id") or 0)
        if not other:
            return

        join_room(dm_room(me, other))

        # mark messages from other -> me as READ when I open chat
        try:
            unread_ids = db_helper.get_unread_ids(other, me)
            if unread_ids:
                db_helper.mark_read_for_chat(other, me)
            # Notify the sender of ALL their messages that are now read
            # (includes previously-read ones so old grey ticks on sender's screen update)
            conn = db_helper.get_connection()
            try:
                all_read_ids = [r["id"] for r in conn.execute("""
                    SELECT id FROM messages
                    WHERE sender_id=? AND receiver_id=?
                    AND region_name IS NULL AND read_at IS NOT NULL
                """, (other, me)).fetchall()]
            finally:
                conn.close()
            if all_read_ids:
                emit("dm_read", {"ids": all_read_ids}, room=dm_room(me, other))
            if unread_ids:
                # Clear my own badge for this sender
                emit("badge_update", {"from_id": other, "count": 0}, room=request.sid)
        except Exception:
            pass

    @socketio.on("dm_mark_read")
    def dm_mark_read(data):
        """Receiver emits this when a new message arrives and they're already in the chat."""
        if "user_id" not in session:
            return
        me = int(session["user_id"])
        sender_id = int((data or {}).get("sender_id") or 0)
        msg_id = (data or {}).get("msg_id")
        if not sender_id or not msg_id:
            return
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db_helper.mark_read_for_chat(sender_id, me, ts)
            emit("dm_read", {"ids": [msg_id]}, room=dm_room(me, sender_id))
            emit("badge_update", {"from_id": sender_id, "count": 0}, room=request.sid)
        except Exception:
            pass

    @socketio.on("dm_send_message")
    def dm_send_message(data):
        if "user_id" not in session:
            return

        sender_id = int(session["user_id"])
        receiver_id = int((data or {}).get("receiver_id") or 0)
        message_type = ((data or {}).get("message_type") or "text").strip().lower()
        message_text = ((data or {}).get("message_text") or "").strip()
        media_path = ((data or {}).get("media_path") or "").strip()
        audio_path = ((data or {}).get("audio_path") or "").strip()
        file_name = ((data or {}).get("file_name") or "").strip()
        temp_key  = (data or {}).get("_tempKey")

        if not receiver_id:
            return

        if message_type == "text" and not message_text:
            return
        if message_type == "image" and not media_path:
            return
        if message_type == "audio" and not audio_path:
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        msg_id = db_helper.save_message(
            sender_id=sender_id,
            receiver_id=receiver_id,
            region_name=None,
            message_type=message_type,
            message_text=message_text,
            media_path=media_path,
            audio_path=audio_path,
            file_name=file_name,
            timestamp=ts
        )

        payload = {
            "id": msg_id,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "message_type": message_type,
            "message_text": message_text,
            "media_path": media_path,
            "audio_path": audio_path,
            "file_name": file_name,
            "timestamp": ts,
            "delivered_at": None,
            "read_at": None,
            "_tempKey": temp_key
        }

        emit("dm_receive_message", payload, room=dm_room(sender_id, receiver_id))

        # ✅ delivered if receiver online
        if receiver_id in online_users:
            try:
                db_helper.mark_delivered(msg_id, ts)
                emit("dm_delivered", {"id": msg_id, "delivered_at": ts}, room=dm_room(sender_id, receiver_id))
            except Exception:
                pass

        # 🔔 push badge count update to the receiver so their sidebar updates live
        try:
            receiver_sid = online_users.get(receiver_id)
            if receiver_sid:
                # count unread from this sender for the receiver
                unread_ids = db_helper.get_unread_ids(sender_id, receiver_id)
                socketio.emit("badge_update", {
                    "from_id": sender_id,
                    "count": len(unread_ids)
                }, to=receiver_sid)
        except Exception:
            pass

# =========================
# Blueprint + HTTP routes
# =========================

messaging_bp = Blueprint("messaging", __name__, url_prefix="/messages")

UPLOAD_IMG_FOLDER = "static/uploads/chat_images"
UPLOAD_AUDIO_FOLDER = "static/uploads/chat_audio"
os.makedirs(UPLOAD_IMG_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_AUDIO_FOLDER, exist_ok=True)

ALLOWED_IMG = {"png", "jpg", "jpeg", "webp", "gif"}
ALLOWED_AUDIO = {"mp3", "wav", "m4a", "ogg", "webm"}


def _ext_ok(filename, allowed):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in allowed


def _my_uid():
    return int(session.get("user_id", 1))


def _get_user_basic(uid: int):
    conn = db_helper.get_connection()
    try:
        row = conn.execute("""
            SELECT u.id, u.username, u.role,
                   COALESCE(p.profile_pic, 'profile_pic.png') AS pfp
            FROM users u
            LEFT JOIN profiles p ON p.user_id = u.id
            WHERE u.id = ?
        """, (uid,)).fetchone()
    finally:
        conn.close()

    if not row:
        return {"id": uid, "username": f"user{uid}", "role": "unknown", "pfp": "profile_pic.png"}

    return {
        "id": row["id"],
        "username": row["username"] or f"user{uid}",
        "role": (row["role"] or "unknown"),
        "pfp": row["pfp"] or "profile_pic.png",
    }


def _get_people_for_sidebar(me_id: int, my_role: str):
    conn = db_helper.get_connection()
    try:
        rows = conn.execute("""
            SELECT u.id, u.username, u.role,
                   COALESCE(p.profile_pic, 'profile_pic.png') AS pfp,
                   MAX(m.timestamp) AS last_msg
            FROM users u
            LEFT JOIN profiles p ON p.user_id = u.id
            LEFT JOIN messages m
                ON m.region_name IS NULL
                AND (
                    (m.sender_id = u.id   AND m.receiver_id = ?)
                 OR (m.sender_id = ?     AND m.receiver_id = u.id)
                )
            WHERE u.id != ?
            GROUP BY u.id
            ORDER BY last_msg DESC, u.username ASC
        """, (me_id, me_id, me_id)).fetchall()
    finally:
        conn.close()

    people = []
    my_role = (my_role or "").lower().strip()

    for r in rows:
        role = (r["role"] or "").lower().strip()
        if my_role == "youth" and role == "senior":
            people.append({"id": r["id"], "username": r["username"], "role": role, "pfp": r["pfp"]})
        elif my_role == "senior" and role == "youth":
            people.append({"id": r["id"], "username": r["username"], "role": role, "pfp": r["pfp"]})

    return people


@messaging_bp.route("/")
def inbox():
    uid = _my_uid()
    me = _get_user_basic(uid)
    people = _get_people_for_sidebar(uid, me.get("role"))

    try:
        unread_counts = db_helper.get_unread_counts(uid)
    except Exception:
        unread_counts = {}

    for p in people:
        p["unread"] = unread_counts.get(p["id"], 0)

    return render_template("messages/inbox.html", me=me, people=people)


@messaging_bp.route("/chat/<int:other_id>")
def chat(other_id):
    uid = _my_uid()
    me = _get_user_basic(uid)
    other = _get_user_basic(other_id)
    people = _get_people_for_sidebar(uid, me.get("role"))

    # ✅ Mark messages from other person as read
    try:
        db_helper.mark_read(sender_id=other_id, receiver_id=uid)
    except Exception:
        pass

    try:
        unread_counts = db_helper.get_unread_counts(uid)
    except Exception:
        unread_counts = {}

    for p in people:
        # active chat partner already marked read above
        p["unread"] = unread_counts.get(p["id"], 0) if p["id"] != other_id else 0

    # Load conversation
    messages = []
    try:
        messages = db_helper.get_chat_history(uid, other_id)
    except Exception:
        messages = []

    return render_template(
        "messages/chat.html",
        me=me,
        conversations=people,
        current_user_id=uid,
        other_user=other,
        messages=messages,
        active_id=other_id,
    )


@messaging_bp.route("/upload/image", methods=["POST"])
def upload_image():
    f = request.files.get("image")
    if not f or f.filename == "":
        return jsonify({"ok": False, "error": "No file"}), 400

    if not _ext_ok(f.filename, ALLOWED_IMG):
        return jsonify({"ok": False, "error": "Invalid image type"}), 400

    filename = secure_filename(f.filename)
    unique = f"{uuid.uuid4().hex}_{filename}"
    save_path = os.path.join(UPLOAD_IMG_FOLDER, unique)
    f.save(save_path)

    rel = f"uploads/chat_images/{unique}"
    return jsonify({"ok": True, "media_path": rel})


@messaging_bp.route("/upload/audio", methods=["POST"])
def upload_audio():
    f = request.files.get("audio")
    if not f or f.filename == "":
        return jsonify({"ok": False, "error": "No file"}), 400

    if not _ext_ok(f.filename, ALLOWED_AUDIO):
        return jsonify({"ok": False, "error": "Invalid audio type"}), 400

    filename = secure_filename(f.filename)
    unique = f"{uuid.uuid4().hex}_{filename}"
    save_path = os.path.join(UPLOAD_AUDIO_FOLDER, unique)
    f.save(save_path)

    rel = f"uploads/chat_audio/{unique}"
    return jsonify({"ok": True, "audio_path": rel})


# (Optional) Group chat route placeholder
@messaging_bp.route("/group/<region>")
def group_chat(region):
    uid = _my_uid()
    me = _get_user_basic(uid)
    people = _get_people_for_sidebar(uid, me.get("role"))

    groups = [
        {"region": "north", "name": "North Region Group"},
        {"region": "east", "name": "East Region Group"},
        {"region": "central", "name": "Central Region Group"},
        {"region": "west", "name": "West Region Group"},
    ]

    messages = []
    return render_template(
        "messages/group_chat.html",
        me=me,
        people=people,
        groups=groups,
        region=region,
        active_id=None,
        active_group=region,
        messages=messages,
    )