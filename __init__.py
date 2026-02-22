from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from database import db_helper
import sqlite3
import os
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash # <--- jiawen added this
from features.story import story_bp
from features.garden import garden_bp 
import re
import random
from flask_socketio import SocketIO, join_room, emit
from functools import wraps
from features.messaging import messaging_bp
from features.messaging import init_messaging



os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
# Initialize the Flask application
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
init_messaging(socketio)
# Secret key is required to use 'session' (it encrypts the cookie)
app.secret_key = 'winx_club_secret'

app.register_blueprint(story_bp)
app.register_blueprint(garden_bp)
app.register_blueprint(messaging_bp)
# Setup upload folder
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


# ADMIN
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.")
            return redirect(url_for("login"))

        if (session.get("role") or "").strip().lower() != "admin":
            flash("You do not have permission to access the admin page.")
            return redirect(url_for("home"))  # or url_for("story.index")
        return f(*args, **kwargs)
    return decorated_function

# --- HOME ROUTE ---
@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('story.index'))

# --- SIGNUP ROUTE ---  (UPDATED)
def is_valid_password(password):
    return (
        len(password) >= 8 and
        re.search(r"[A-Z]", password) and
        re.search(r"[a-z]", password) and
        re.search(r"\d", password)
    )
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', '').strip()
        region = request.form.get('region', '').strip()
        email = request.form.get('email', '').strip()
        bio = request.form.get('bio', '').strip()

        # Required field check
        if not name or not username or not password or not role or not region or not email:
            flash("Please fill in all required fields.")
            return render_template('profile/signup.html')

        # Password strength validation
        if not is_valid_password(password):
            flash(
                "Password must be at least 8 characters long and include "
                "an uppercase letter, a lowercase letter, and a number."
            )
            return render_template('profile/signup.html')

        # Hash the password
        hashed_password = generate_password_hash(password)

        conn = db_helper.get_connection()
        try:
            # Insert into users table
            cur = conn.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, hashed_password, role)
            )
            user_id = cur.lastrowid

            # Insert into profiles table
            conn.execute(
                "INSERT INTO profiles (user_id, name, region, email, bio) VALUES (?, ?, ?, ?, ?)",
                (user_id, name, region, email, bio)
            )

            conn.commit()

            db_helper.add_notice(
                username=username,
                region=region,
                emoji="🧑‍🤝‍🧑",
                message=f"New Member:<b>{username}</b> just joined the {region} community today!"
            )

            flash("Account created successfully! Please log in.")
            return redirect(url_for('login'))


        except sqlite3.IntegrityError:
            flash("Username already exists. Please choose another.")
            return render_template('profile/signup.html')

        finally:
            conn.close()

    return render_template('profile/signup.html')

# --- LOGIN ROUTE ---   (UPDATED)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_input = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        # 1. Try to find the user in the database
        user = db_helper.get_user_by_login(login_input)

        if not user:
            flash("Username or email not found.")
        else:
            # 2. Use check_password_hash because the DB now has scrambled text
            if check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                
                return redirect(url_for('story.index'))   

            else:
                flash("Incorrect password.")
                
    return render_template('profile/login.html')

# --- PROFILE ROUTE ---   (UPDATED)
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('story.index'))

    conn = db_helper.get_connection()
    try:
        # profile info
        query = """
            SELECT u.username, u.role, p.* 
            FROM users u
            JOIN profiles p ON u.id = p.user_id
            WHERE u.id = ?
        """
        user_data = conn.execute(query, (session['user_id'],)).fetchone()

        # user stories (only their own)
        stories = conn.execute("""
            SELECT s.*
            FROM stories s
            WHERE s.user_id = ?
            ORDER BY s.created_at DESC
        """, (session['user_id'],)).fetchall()

    finally:
        conn.close()

    if user_data is None:
        return redirect(url_for('logout'))

    return render_template('profile/profile.html', profile=user_data, stories=stories, is_own_profile=True)


# --- EDIT PROFILE ROUTE --- (MERGED: role update + region change notices)
@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = db_helper.get_connection()

    try:
        if request.method == 'POST':
            new_name = request.form.get('name', '').strip()
            new_bio = request.form.get('bio', '').strip()
            new_region = request.form.get('region', '').strip()
            new_role = request.form.get('role', '').strip()

            file = request.files.get('profile_image')

            # ✅ Get old region BEFORE updating
            old_row = conn.execute(
                "SELECT region FROM profiles WHERE user_id = ?",
                (session['user_id'],)
            ).fetchone()
            old_region = (old_row["region"] if old_row else None) or "Unknown"

            # 1) Image Update Logic
            if file and file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                conn.execute(
                    "UPDATE profiles SET profile_pic = ? WHERE user_id = ?",
                    (filename, session['user_id'])
                )

            # 2) Update Profiles Table
            conn.execute(
                "UPDATE profiles SET name = ?, bio = ?, region = ? WHERE user_id = ?",
                (new_name, new_bio, new_region, session['user_id'])
            )

            # 3) Update Users Table (Role)
            conn.execute(
                "UPDATE users SET role = ? WHERE id = ?",
                (new_role, session['user_id'])
            )

            conn.commit()

            # ✅ Add notices if region changed
            if new_region and old_region != new_region:
                username = session.get("username", "Someone")

                db_helper.add_notice(
                    username=username,
                    region=old_region,
                    emoji="🚪",
                    message=f"<b>{username}</b> has left the {old_region} community."
                )

                db_helper.add_notice(
                    username=username,
                    region=new_region,
                    emoji="🧑‍🤝‍🧑",
                    message=f"<b>{username}</b> just joined the {new_region} community today!"
                )

            # Keep session synced
            session['role'] = new_role

            flash("Profile updated!")
            return redirect(url_for('profile'))

        # -------- GET: load existing data --------
        user_data = conn.execute("""
            SELECT u.role, p.name, p.bio, p.region, p.profile_pic
            FROM users u
            JOIN profiles p ON u.id = p.user_id
            WHERE u.id = ?
        """, (session['user_id'],)).fetchone()

        return render_template('profile/edit_profile.html', profile=user_data)

    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
        return redirect(url_for('edit_profile'))

    finally:
        conn.close()



# --- REMOVE PHOTO ---
@app.route('/remove_photo', methods=['POST'])
def remove_photo():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = db_helper.get_connection()
    try:
        # Reset to default
        conn.execute("UPDATE profiles SET profile_pic = 'profile_pic.png' WHERE user_id = ?", 
                     (session['user_id'],))
        conn.commit()
        flash("Photo removed successfully!")
    except Exception as e:
        flash(f"Error: {e}")
    finally:
        conn.close()
    
    # Redirect back to edit page
    return redirect(url_for('edit_profile'))

# --- SETTINGS ---
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = db_helper.get_connection()
    
    if request.method == 'POST':
        allowed_fields = {
            'show_email', 'show_region', 'community_visible',
            'notify_messages', 'notify_updates', 'notify_events',
            'notify_comm', 'notify_inapp'
        }

        # update ONLY fields that came in this request
        for field in request.form:
            if field in allowed_fields:
                value = int(request.form.get(field, 0))  # expects "0" or "1"
                conn.execute(
                    f"UPDATE profiles SET {field} = ? WHERE user_id = ?",
                    (value, session['user_id'])
                )

        conn.commit()
        return ("", 204)
        
    user_data = conn.execute("SELECT * FROM profiles WHERE user_id = ?", 
                             (session['user_id'],)).fetchone()
    conn.close()
    return render_template('profile/settings.html', settings=user_data)

# --- DELETE ACCOUNT ---
@app.route('/delete_account', methods=['POST'])
def delete_account():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    uid = session['user_id']
    conn = db_helper.get_connection()
    try:
        # 1) Get username + region BEFORE deleting
        row = conn.execute("""
            SELECT u.username, p.region
            FROM users u
            JOIN profiles p ON u.id = p.user_id
            WHERE u.id = ?
        """, (uid,)).fetchone()

        if row:
            username = row["username"]
            region = row["region"] or "Unknown"

            # 2) Add "left" notice (this stays in DB)
            db_helper.add_notice(
                username=username,
                region=region,
                emoji="🚪",
                message=f"<b>{username}</b> has left the {region} community."
            )

        # Delete from all tables to avoid errors for your team
        conn.execute("DELETE FROM profiles WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()

        session.clear()
        flash("Account deleted.")
    finally:
        conn.close()
    return redirect(url_for('signup'))

# --- MAIL ---
from flask_mail import Mail, Message
# ===== MAIL CONFIG =====
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False

# Use environment variables (IMPORTANT)
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')

mail = Mail(app)

# --- SEND VERIFICATION CODE (EMAIL OTP) ---
def send_verification_code(email):
    code = str(random.randint(100000, 999999))  # 6-digit code

    session['reset_code'] = code
    session['reset_code_expiry'] = (
        datetime.now() + timedelta(minutes=10)
    ).isoformat()
    session['reset_email'] = email

    msg = Message(
        subject="Your Password Reset Code – The Legacy Garden 🌱",
        recipients=[email]
    )

    msg.body = f"""
Hi,

Your password reset verification code is:

{code}

This code will expire in 10 minutes.

If you did not request this, please ignore this email.
"""

    mail.send(msg)
    
# --- RESET PASSWORD ---   (UPDATED)
@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    error = None

    if request.method == 'POST':
        action = request.form.get('action')

        # ===============================
        # STEP 1: SEND VERIFICATION CODE
        # ===============================
        if action == 'send_code':
            login_input = request.form.get('login_input', '').strip()

            conn = db_helper.get_connection()
            try:
                user = conn.execute(
                    """
                    SELECT p.email 
                    FROM users u 
                    JOIN profiles p ON u.id = p.user_id 
                    WHERE u.username = ? OR p.email = ?
                    """,
                    (login_input, login_input)
                ).fetchone()
            finally:
                conn.close()

            if user:
                send_verification_code(user['email'])
                flash("Verification code sent to your email.")
            else:
                error = "Username or email not found."

        # ===============================
        # STEP 2: VERIFY CODE + RESET
        # ===============================
        elif action == 'reset_password':
            entered_code = request.form.get('verification_code', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()

            # Validation checks
            if new_password != confirm_password:
                error = "Passwords do not match."
            elif entered_code != session.get('reset_code'):
                error = "Invalid verification code."
            elif datetime.now() > datetime.fromisoformat(session.get('reset_code_expiry')):
                error = "Verification code has expired."
            else:
                hashed_pw = generate_password_hash(new_password)

                conn = db_helper.get_connection()
                try:
                    conn.execute(
                        """
                        UPDATE users 
                        SET password = ? 
                        WHERE id = (
                            SELECT u.id 
                            FROM users u 
                            JOIN profiles p ON u.id = p.user_id 
                            WHERE p.email = ?
                        )
                        """,
                        (hashed_pw, session.get('reset_email'))
                    )
                    conn.commit()
                finally:
                    conn.close()

                session.clear()
                flash("Password updated successfully!")
                return redirect(url_for('login'))

    return render_template('profile/reset_password.html', error=error)

# --- RESET PASSWORD FOR SETTINGS ---   (UPDATED)
@app.route('/reset_password_settings', methods=['GET', 'POST'])
def reset_password_settings():
    error = None

    if request.method == 'POST':
        action = request.form.get('action')

        # ===============================
        # STEP 1: SEND VERIFICATION CODE
        # ===============================
        if action == 'send_code':
            login_input = request.form.get('login_input', '').strip()

            conn = db_helper.get_connection()
            try:
                user = conn.execute(
                    """
                    SELECT p.email 
                    FROM users u 
                    JOIN profiles p ON u.id = p.user_id 
                    WHERE u.username = ? OR p.email = ?
                    """,
                    (login_input, login_input)
                ).fetchone()
            finally:
                conn.close()

            if user:
                send_verification_code(user['email'])
                flash("Verification code sent to your email.")
            else:
                error = "Username or email not found."

# ===============================
        # STEP 2: VERIFY CODE + RESET
        # ===============================
        elif action == 'reset_password':
            entered_code = request.form.get('verification_code', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()

            # Validation checks
            if new_password != confirm_password:
                error = "Passwords do not match."
            elif entered_code != session.get('reset_code'):
                error = "Invalid verification code."
            elif datetime.now() > datetime.fromisoformat(session.get('reset_code_expiry')):
                error = "Verification code has expired."
            else:
                hashed_pw = generate_password_hash(new_password)

                conn = db_helper.get_connection()
                try:
                    conn.execute(
                        """
                        UPDATE users 
                        SET password = ? 
                        WHERE id = (
                            SELECT u.id 
                            FROM users u 
                            JOIN profiles p ON u.id = p.user_id 
                            WHERE p.email = ?
                        )
                        """,
                        (hashed_pw, session.get('reset_email'))
                    )
                    conn.commit()
                finally:
                    conn.close()

                session.clear()
                flash("Password updated successfully!")
                return redirect(url_for('login'))

    return render_template('profile/reset_password_settings.html', error=error)

# --- CHANGE EMAIL ---
@app.route('/change_email', methods=['GET', 'POST'])
def change_email():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        new_email = request.form.get('new_email', '').strip().lower()
        user_id = session['user_id']

        if not password or not new_email:
            flash("Please fill in all fields.")
            return render_template('profile/change_email.html')

        conn = db_helper.get_connection()
        try:
            # Get current password + current email
            user = conn.execute(
                """
                SELECT u.password, p.email
                FROM users u
                JOIN profiles p ON u.id = p.user_id
                WHERE u.id = ?
                """,
                (user_id,)
            ).fetchone()

            if not user:
                flash("User not found.")
                return render_template('profile/change_email.html')

            # Verify password
            if not check_password_hash(user['password'], password):
                flash("Incorrect password. Verification failed.")
                return render_template('profile/change_email.html')

            # SAME EMAIL VALIDATION
            if new_email == user['email'].lower():
                flash("You are already using this email address.")
                return render_template('profile/change_email.html')

            # Check if email already exists
            email_exists = conn.execute(
                "SELECT id FROM profiles WHERE email = ?",
                (new_email,)
            ).fetchone()

            if email_exists:
                flash("This email is already in use by another account.")
                return render_template('profile/change_email.html')

            # Update email
            conn.execute(
                "UPDATE profiles SET email = ? WHERE user_id = ?",
                (new_email, user_id)
            )
            conn.commit()

            flash("Email updated successfully!")
            return redirect(url_for('profile'))

        except Exception as e:
            flash("Error updating email. Please try again.")
        finally:
            conn.close()

    return render_template('profile/change_email.html')

# --- TERMS AND PRIVACY --- (JIAWEN - NEWLY ADDED)
@app.route('/terms')
def terms():
    return render_template('profile/terms.html')

# --- COMMUNITY GUIDELINES --- (JIAWEN - NEWLY ADDED)
@app.route("/community_guidelines")
def community_guidelines():
    return render_template("profile/community_guidelines.html")

# --- 6. LOGOUT ROUTE ---
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


def get_tree_stage(points):
    if points >= 300:
        return "Flourishing Stage"
    elif points >= 150:
        return "Growing Stage"
    elif points >= 50:
        return "Budding Stage"
    else:
        return "Seedling Stage"


def get_tree_image(points):
    if points >= 300:
        return "tree_flourishing.png"
    elif points >= 150:
        return "tree_growing.png"
    elif points >= 50:
        return "tree_budding.png"
    else:
        return "tree_seedling.png"

# =========================
# ADMIN ACCESS DECORATOR
# =========================
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("role", "").lower() != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = db_helper.get_connection()

    # ----- STORIES LIST -----
    stories = conn.execute("""
        SELECT 
            s.id,
            s.title,
            s.content,
            s.image_path,
            s.status,
            u.username,
            r.reason AS report_reason
        FROM stories s
        JOIN users u ON s.user_id = u.id
        LEFT JOIN reports r ON s.id = r.story_id
        WHERE s.status != 'approved'
        ORDER BY s.created_at DESC
    """).fetchall()

    # ----- STORIES COUNT -----
    story_count = conn.execute("""
        SELECT COUNT(*) 
        FROM stories 
        WHERE status != 'approved'
    """).fetchone()[0]

    # ----- REPORTED COMMENTS -----      ← ADD THIS BLOCK
    reported_comments = conn.execute("""
        SELECT 
            sc.id,
            sc.content,
            u.username,
            s.title AS story_title,
            cr.reason AS report_reason
        FROM comment_reports cr
        JOIN story_comments sc ON cr.comment_id = sc.id
        JOIN users u ON sc.user_id = u.id
        JOIN stories s ON sc.story_id = s.id
        ORDER BY cr.created_at DESC
    """).fetchall()

    # ----- EVENTS COUNT (SAFE) -----
    try:
        event_count = conn.execute("""
            SELECT COUNT(*) 
            FROM events 
            WHERE status IN ('pending', 'reported')
        """).fetchone()[0]
    except sqlite3.OperationalError:
        event_count = 0

    conn.close()

    return render_template(
        "admin/admin_dashboard.html",
        stories=stories,
        story_count=story_count,
        event_count=event_count,
        reported_comments=reported_comments,  
    )


# =========================
# ADMIN – APPROVE STORY
# =========================
@app.route("/admin/approve/<int:story_id>", methods=["POST"])
@admin_required
def approve_story(story_id):
    conn = db_helper.get_connection()

    conn.execute("""
        UPDATE stories
        SET status = 'approved'
        WHERE id = ?
    """, (story_id,))

    conn.execute("""
        DELETE FROM reports
        WHERE story_id = ?
    """, (story_id,))

    conn.commit()
    conn.close()

    flash("Story approved successfully")
    return redirect(url_for("admin_dashboard"))

# =========================
# ADMIN – DELETE STORY
# =========================
@app.route("/admin/delete/<int:story_id>", methods=["POST"])
@admin_required
def delete_story(story_id):
    conn = db_helper.get_connection()

    conn.execute("DELETE FROM reports WHERE story_id = ?", (story_id,))
    conn.execute("DELETE FROM story_likes WHERE story_id = ?", (story_id,))
    conn.execute("DELETE FROM story_comments WHERE story_id = ?", (story_id,))
    conn.execute("DELETE FROM stories WHERE id = ?", (story_id,))

    conn.commit()
    conn.close()

    flash("Story deleted successfully")
    return redirect(url_for("admin_dashboard"))

# =========================
# ADMIN – APPROVE COMMENT
# =========================
@app.route("/admin/approve_comment/<int:comment_id>", methods=["POST"])
@admin_required
def approve_comment(comment_id):
    conn = db_helper.get_connection()
    conn.execute("DELETE FROM comment_reports WHERE comment_id = ?", (comment_id,))
    conn.commit()
    conn.close()
    flash("Comment approved (report dismissed)")
    return redirect(url_for("admin_dashboard"))

# =========================
# ADMIN – DELETE COMMENT
# =========================
@app.route("/admin/delete_comment/<int:comment_id>", methods=["POST"])
@admin_required
def delete_comment_admin(comment_id):
    conn = db_helper.get_connection()
    conn.execute("DELETE FROM comment_reports WHERE comment_id = ?", (comment_id,))
    conn.execute("DELETE FROM story_comments WHERE id = ?", (comment_id,))
    conn.commit()
    conn.close()
    flash("Comment deleted successfully")
    return redirect(url_for("admin_dashboard"))

# =========================
# ADMIN – EVENTS
# =========================
@app.route("/admin/events")
@admin_required
def admin_events():
    conn = db_helper.get_connection()

    events = conn.execute("""
        SELECT 
            e.*,
            u.username
        FROM events e
        LEFT JOIN users u ON e.created_by = u.id
        ORDER BY e.created_at DESC
    """).fetchall()

    conn.close()

    return render_template("admin/admin_events.html", events=events)


# =========================
# ADMIN – ADD EVENT
# =========================
@app.route("/admin/events/add", methods=["POST"])
@admin_required
def add_event():
    conn = db_helper.get_connection()

    title = request.form.get("title")
    event_date = request.form.get("event_date")
    short_desc = request.form.get("short_description")
    full_desc = request.form.get("full_description")
    status = request.form.get("status")

    image_file = request.files.get("image")
    filename = None

    if image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        image_path = os.path.join("static", "uploads", filename)
        image_file.save(image_path)

    conn.execute("""
        INSERT INTO events (
            title,
            short_description,
            full_description,
            event_date,
            image_filename,
            status,
            created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        title,
        short_desc,
        full_desc,
        event_date,
        filename,
        status,
        session["user_id"]
    ))

    conn.commit()
    conn.close()

    return redirect(url_for("admin_events"))

# =========================
# ADMIN – EDIT EVENT
# =========================
@app.route("/admin/events/edit/<int:event_id>", methods=["GET", "POST"])
@admin_required
def edit_event(event_id):
    conn = db_helper.get_connection()

    event = conn.execute(
        "SELECT * FROM events WHERE id = ?",
        (event_id,)
    ).fetchone()

    if not event:
        conn.close()
        return redirect(url_for("admin_events"))

    if request.method == "POST":

        title = request.form.get("title")
        event_date = request.form.get("event_date")
        short_description = request.form.get("short_description")
        full_description = request.form.get("full_description")
        status = request.form.get("status")

        image_file = request.files.get("image")

        if image_file and image_file.filename != "":
            filename = secure_filename(image_file.filename)
            image_path = os.path.join("static/uploads", filename)
            image_file.save(image_path)

            conn.execute("""
                UPDATE events
                SET title=?, event_date=?, short_description=?,
                    full_description=?, status=?, image_filename=?
                WHERE id=?
            """, (title, event_date, short_description,
                  full_description, status, filename, event_id))
        else:
            conn.execute("""
                UPDATE events
                SET title=?, event_date=?, short_description=?,
                    full_description=?, status=?
                WHERE id=?
            """, (title, event_date, short_description,
                  full_description, status, event_id))

        conn.commit()
        conn.close()
        return redirect(url_for("admin_events"))

    conn.close()
    return render_template("admin/edit_event.html", event=event)


# =========================
# ADMIN – DELETE
# =========================
@app.route("/admin/events/delete/<int:event_id>", methods=["POST"])
@admin_required
def delete_event_admin(event_id):
    conn = db_helper.get_connection()
    conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("admin_events"))


# =========================
# VIEW PROFILE
# =========================
@app.route('/view_profile/<username>')
def view_profile(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    print(f"\n🔍 DEBUG view_profile:")
    print(f"  Requested username: {username}")
    print(f"  Session user_id: {session.get('user_id')}")
    print(f"  Session username: {session.get('username')}")

    conn = db_helper.get_connection()
    try:
        # ✅ Get the VIEWED user's profile data
        user_data = conn.execute("""
            SELECT u.id, u.username, u.role, u.points,
                   p.user_id, p.name, p.bio, p.region, p.profile_pic, p.email,
                   p.community_visible, p.show_email, p.show_region
            FROM users u
            JOIN profiles p ON u.id = p.user_id
            WHERE u.username = ?
        """, (username,)).fetchone()

        print(f"  Query result: {user_data is not None}")

        if not user_data:
            print(f"  ❌ User '{username}' not found in database!")
            flash(f"User '{username}' not found.")
            return redirect(url_for('story.index'))

        user_data = dict(user_data)
        print(f"  ✅ Found user: id={user_data['id']}, username={user_data['username']}")

        # ✅ Check if viewing own profile
        is_own_profile = (user_data['id'] == session['user_id'])
        print(f"  is_own_profile: {is_own_profile}")

        # ✅ Privacy check
        if not user_data.get('community_visible', 1) and not is_own_profile:
            print("  ❌ Profile is private")
            flash("This profile is private.")
            return redirect(url_for('story.index'))

        # ✅ Fetch stories WITH like & comment counts + user_liked
        viewer_id = session.get("user_id")

        stories = conn.execute("""
            SELECT s.*,
                   COALESCE(lc.like_count, 0) AS like_count,
                   COALESCE(cc.comment_count, 0) AS comment_count,
                   CASE WHEN ul.user_id IS NULL THEN 0 ELSE 1 END AS user_liked
            FROM stories s
            LEFT JOIN (
                SELECT story_id, COUNT(*) AS like_count
                FROM story_likes
                GROUP BY story_id
            ) lc ON lc.story_id = s.id
            LEFT JOIN (
                SELECT story_id, COUNT(*) AS comment_count
                FROM story_comments
                GROUP BY story_id
            ) cc ON cc.story_id = s.id
            LEFT JOIN story_likes ul
                ON ul.story_id = s.id AND ul.user_id = ?
            WHERE s.user_id = ? AND s.status = 'approved'
            ORDER BY s.created_at DESC
        """, (viewer_id, user_data['id'])).fetchall()

        stories = [dict(s) for s in stories]
        print(f"  ✅ Found {len(stories)} stories")

        # ✅ Apply privacy masking (for non-own profile)
        if not is_own_profile:
            if not user_data.get('show_email', 1):
                user_data['email'] = None
            if not user_data.get('show_region', 1):
                user_data['region'] = None

        print("  ✅ Rendering view_profile.html")

        return render_template(
            'profile/view_profile.html',
            profile=user_data,
            user=user_data,          # ✅ from your 2nd route (prevents template crash)
            stories=stories,
            is_own_profile=is_own_profile
        )

    except Exception as e:
        print(f"  ❌ EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading profile: {e}")
        return redirect(url_for('story.index'))
    finally:
        conn.close()



# Fel added
# --- 3. COMMUNITY DASHBOARD ---
@app.route('/community')
def community():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_user_id = session['user_id']
    profile = db_helper.get_profile_by_user_id(current_user_id) or {"region": "Unknown"}
    region_name = profile.get("region", "Unknown")

    youth_members, senior_members, total_members = db_helper.get_region_member_counts(region_name)

    last_notice_update = db_helper.get_latest_notice_timestamp(region_name)
    notices = db_helper.get_region_notices(region_name, limit=3)
    latest_notice = notices[0] if notices else None   # keep as dict, no comma

    achievement_last_update = get_last_monday()
    week_start_dt = achievement_last_update
    week_end_dt = week_start_dt + timedelta(days=7)
    week_start_str = week_start_dt.strftime("%Y-%m-%d")

    weekly = db_helper.get_weekly_achievements(week_start_str)

    # latest notice this week (any region)
    latest_notice_this_week = db_helper.get_latest_notice_timestamp_in_range(week_start_dt, week_end_dt)

    trees_harvested, flowers_harvested, community_points = db_helper.get_region_tree_totals(region_name)

    tree_stage = get_tree_stage(community_points)   
    tree_image = get_tree_image(community_points)


    should_recompute = False

    if not weekly:
        should_recompute = True
    else:
        # weekly["generated_at"] is SQLite CURRENT_TIMESTAMP (UTC)
        gen = weekly.get("generated_at")
        if gen and latest_notice_this_week:
            generated_at_dt = datetime.strptime(gen, "%Y-%m-%d %H:%M:%S")
            # if your notices/generate_at are UTC, compare directly
            if latest_notice_this_week > generated_at_dt:
                should_recompute = True

    if should_recompute:
        most_active, participation, best_harvest = db_helper.compute_weekly_winners(
                week_start_dt, week_end_dt
            )

        db_helper.save_weekly_achievements(
            week_start_str, most_active, participation, best_harvest
        )
        weekly = db_helper.get_weekly_achievements(week_start_str)


    # IMPORTANT: pass acceptance flag
    guidelines_accepted = int(profile.get("guidelines_accepted") or 0)

    my_username = session.get("username", "")
    my_region = (profile.get("region") or "Unknown")

    return render_template(
        'community/community.html',
        profile=profile,
        youth_members=youth_members,
        senior_members=senior_members,
        total_members=total_members,

        last_notice_update=last_notice_update,
        notices=notices,
        latest_notice=latest_notice,

        achievement_last_update=achievement_last_update,
        most_active_region=weekly["most_active_region"],
        best_harvest_region=weekly["best_harvest_region"],
        participation_region=weekly["participation_region"],
            
        guidelines_accepted=guidelines_accepted,

        trees_harvested=trees_harvested,
        flowers_harvested=flowers_harvested,
        community_points=community_points,

        stage=tree_stage,
        tree_image=tree_image,

        # ✅ ADD THESE TWO
        my_username=my_username,
        my_region=my_region,
    )



@app.route("/community/accept_guidelines", methods=["POST"])
def accept_guidelines():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = db_helper.get_connection()
    try:
        conn.execute("""
            UPDATE profiles
            SET guidelines_accepted = 1,
                guidelines_accepted_at = ?
            WHERE user_id = ?
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session["user_id"]))
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("community"))


@app.template_filter("time_ago")
def time_ago(dt):
    if dt is None:
        return "No recent activity"

    # SQLite CURRENT_TIMESTAMP is UTC, convert to Singapore time
    dt = dt + timedelta(hours=8)

    delta = datetime.now() - dt
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        mins = seconds // 60
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    if seconds < 86400:
        hrs = seconds // 3600
        return f"{hrs} hour{'s' if hrs != 1 else ''} ago"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"



def get_last_monday():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())  # Monday of this week
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)





@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/faq')
def faq():
    return render_template('faq.html')


# Events main page (change yq)
@app.route('/events')
def events_home():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    today_str = get_events_demo_date_str()
    was_reset = db_helper.ensure_weekly_reset(user_id, today_str)

    streaks = db_helper.get_or_create_user_streaks(user_id)

    # 🔥 ADD THIS LINE
    events = db_helper.get_all_events()

    return render_template(
        'events/events.html',
        daily_streak=int(streaks.get("daily_game_streak", 0) or 0),
        win_streak=int(streaks.get("winning_streak", 0) or 0),
        seed_claimed=int(streaks.get("seed_claimed", 0) or 0),
        was_reset=was_reset,
        events=events   # 🔥 VERY IMPORTANT
    )

# Memory Match game
@app.route('/events/memory-match')
def memory_match():
    return render_template('events/memorymatch.html')

@app.route('/events/hangman')
def hangman():
    return render_template('events/hangman.html')

@app.route("/api/streaks/hangman_end", methods=["POST"])
def hangman_end():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json(silent=True) or {}
    did_win = bool(data.get("did_win", False))

    updated = db_helper.update_streaks_on_game_end(session["user_id"], did_win)
    return jsonify(updated)

#Changed
@app.route("/api/streaks/quit_game", methods=["POST"])
def quit_game():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user_id = session["user_id"]
    
    # ✅ Apply both penalties in a single transaction
    conn = db_helper.get_connection()
    try:
        # Ensure user_streaks record exists
        conn.execute("""
            INSERT OR IGNORE INTO user_streaks (user_id, daily_game_streak, winning_streak)
            VALUES (?, 0, 0)
        """, (user_id,))
        
        # Apply penalties: daily_game_streak - 1 (min 0), winning_streak = 0
        conn.execute("""
            UPDATE user_streaks
            SET daily_game_streak = MAX(0, daily_game_streak - 1),
                winning_streak = 0
            WHERE user_id = ?

        """, (user_id,))
        
        conn.commit()
        
        # Fetch and return updated values
        row = conn.execute("""
            SELECT daily_game_streak, winning_streak, last_game_date
            FROM user_streaks
            WHERE user_id = ?
        """, (user_id,)).fetchone()
        
        updated = dict(row) if row else {"daily_game_streak": 0, "winning_streak": 0, "last_game_date": None}
        return jsonify(updated)
    except Exception as e:
        conn.rollback()
        print(f"❌ Error applying quit penalty: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/rewards/claim_seed", methods=["POST"])
def claim_seed():
    if "user_id" not in session:
        return jsonify({"ok": False, "message": "Not logged in"}), 401

    result = db_helper.claim_seed_reward(session["user_id"])
    return jsonify(result)

# vivion
@app.route('/mygarden')
def mygarden():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    uid = session['user_id']

    user_row = db_helper.get_user_by_id(uid)
    user = dict(user_row) if user_row else {}
    user["points"] = int(user.get("points") or 0)

    inventory_row = db_helper.get_user_inventory(uid)
    inventory = dict(inventory_row) if inventory_row else {"seed_tree": 0, "seed_flower": 0, "water": 0}

    plots = db_helper.get_user_plots(uid)
    all_rewards = db_helper.get_all_rewards()
    my_rewards = db_helper.get_user_rewards(uid)

    return render_template(
        'garden/garden_dashboard.html',
        user=user,
        inventory=inventory,
        plots=plots,
        all_rewards=all_rewards,
        my_rewards=my_rewards
    )

# --- zn ---
def friendly_day_label(msg_dt: datetime, now_dt: datetime) -> str:
    msg_date = msg_dt.date()
    now_date = now_dt.date()
    diff_days = (now_date - msg_date).days

    if diff_days == 0:
        return "Today"
    if diff_days == 1:
        return "Yesterday"
    if 2 <= diff_days <= 6:
        return msg_dt.strftime("%A")  # Monday, Tuesday, etc
    return msg_dt.strftime("%d %b %Y")  # fallback e.g. 06 Feb 2026

def get_demo_date_str():
    # if you set a demo date, use it; else use real date
    return session.get("demo_date") or datetime.now().strftime("%Y-%m-%d")

def get_demo_now():
    """
    Returns a datetime.
    If session['demo_date'] exists, return that date with current time.
    Else return real datetime.now().
    """
    demo = session.get("demo_date")
    if not demo:
        return datetime.now()

    # keep time real, only fake the DATE
    now = datetime.now()
    y, m, d = map(int, demo.split("-"))
    return now.replace(year=y, month=m, day=d)
dm_streaks = {}      # { "dm:userA:userB": int }
dm_sent_today = {}   # { "dm:userA:userB": { "userA": bool, "userB": bool } }
dm_last_day = {}     # { "dm:userA:userB": "YYYY-MM-DD" }


# --- Yq --- 
# =========================================================
# EVENTS DEMO HELPERS (ISOLATED FROM DM DEMO)
# =========================================================

def get_events_demo_date_str():
    """
    Returns YYYY-MM-DD.
    Uses events demo date if set, else real date.
    """
    return session.get("events_demo_date") or datetime.now().strftime("%Y-%m-%d")


def get_events_demo_now():
    """
    Returns datetime.
    Fakes DATE only, keeps real time.
    """
    demo = session.get("events_demo_date")
    if not demo:
        return datetime.now()

    now = datetime.now()
    y, m, d = map(int, demo.split("-"))
    return now.replace(year=y, month=m, day=d)
# --- end --- 

# =========================
# DM STREAK PERSISTENCE (SQLite)
# =========================

def ensure_dm_streak_table():
    """
    Creates a small table to persist DM streak state.
    This prevents streaks resetting when server restarts/reloads.
    """
    conn = db_helper.get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dm_streak_state (
                room TEXT PRIMARY KEY,
                streak INTEGER NOT NULL DEFAULT 0,
                last_day TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.commit()
    finally:
        conn.close()


def db_get_dm_state(room: str):
    """
    Returns (streak:int, last_day:str) from DB, defaults (0,'') if missing.
    """
    conn = db_helper.get_connection()
    try:
        row = conn.execute(
            "SELECT streak, last_day FROM dm_streak_state WHERE room = ?",
            (room,)
        ).fetchone()
        if not row:
            return 0, ""
        return int(row["streak"] or 0), (row["last_day"] or "")
    finally:
        conn.close()


def db_set_dm_state(room: str, streak: int, last_day: str):
    """
    Upsert (insert or update) DM streak state.
    """
    conn = db_helper.get_connection()
    try:
        conn.execute("""
            INSERT INTO dm_streak_state (room, streak, last_day)
            VALUES (?, ?, ?)
            ON CONFLICT(room) DO UPDATE SET
                streak = excluded.streak,
                last_day = excluded.last_day
        """, (room, int(streak), str(last_day or "")))
        conn.commit()
    finally:
        conn.close()


# ✅ run once on startup
ensure_dm_streak_table()

print("APP ROOT:", app.root_path)
print("TEMPLATE FOLDER:", app.template_folder)

templates_abs = os.path.join(app.root_path, app.template_folder)
print("TEMPLATES ABS:", templates_abs)

messaging_dir = os.path.join(templates_abs, "messaging")
print("MESSAGING DIR EXISTS?", os.path.exists(messaging_dir))
if os.path.exists(messaging_dir):
    print("FILES IN templates/messaging:", os.listdir(messaging_dir))





# ============================================================
# ✅ DM STREAK PERSISTENCE (SQLite) — prevents reset on reopen
# ============================================================

def ensure_dm_streak_table():
    """
    Create a table to persist DM streak state so it survives reloads/restarts.
    """
    conn = db_helper.get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dm_streak_state (
                room TEXT PRIMARY KEY,
                streak INTEGER NOT NULL DEFAULT 0,
                last_day TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.commit()
    finally:
        conn.close()

def db_get_dm_state(room: str):
    """
    Returns (streak:int, last_day:str). Defaults to (0, '') if missing.
    """
    conn = db_helper.get_connection()
    try:
        row = conn.execute(
            "SELECT streak, last_day FROM dm_streak_state WHERE room = ?",
            (room,)
        ).fetchone()
        if not row:
            return 0, ""
        return int(row["streak"] or 0), (row["last_day"] or "")
    finally:
        conn.close()

def db_set_dm_state(room: str, streak: int, last_day: str):
    """
    Upsert DM state.
    """
    conn = db_helper.get_connection()
    try:
        conn.execute("""
            INSERT INTO dm_streak_state (room, streak, last_day)
            VALUES (?, ?, ?)
            ON CONFLICT(room) DO UPDATE SET
                streak = excluded.streak,
                last_day = excluded.last_day
        """, (room, int(streak), str(last_day or "")))
        conn.commit()
    finally:
        conn.close()

# run once when file loads
ensure_dm_streak_table()



# --- 7. START THE SERVER ---
if __name__ == '__main__':
    socketio.run(app, debug=True)

# =========================
# SOCKET.IO: DM CHAT (ONLINE + STREAKS)
# =========================


def room_name(a: str, b: str) -> str:
    x, y = sorted([a, b])
    return f"dm:{x}:{y}"


def did_complete_today(room: str) -> bool:
    today = get_demo_date_str()
    return dm_last_day.get(room) == today

@socketio.on("typing")
def on_typing(_data=None):
    username = request.args.get("username")
    recipient = request.args.get("recipient")
    if not username or not recipient:
        return

    emit("typing", {"user": username}, room=room_name(username, recipient), include_self=False)


@socketio.on("dm_send_message")
def on_send_message(data):
    sender_username = request.args.get("username")
    recipient_username = (data or {}).get("recipient")
    message_text = ((data or {}).get("message") or "").strip()

    if not sender_username or not recipient_username or not message_text:
        return

    # timestamp + day label (based on demo date)
    now_dt = get_demo_now()
    ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    day_label = friendly_day_label(now_dt, now_dt)

    # save to DB (existing logic)
    conn = db_helper.get_connection()
    try:
        sender_row = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (sender_username,)
        ).fetchone()

        rec_row = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (recipient_username,)
        ).fetchone()

        if not sender_row or not rec_row:
            return

        sender_id = sender_row["id"]
        receiver_id = rec_row["id"]

        db_helper.save_message(sender_id, receiver_id, message_text, timestamp=ts)
    finally:
        conn.close()

    # streak logic (✅ now persistent)
    room = room_name(sender_username, recipient_username)
    today = get_demo_date_str()

    # ✅ load persisted state FIRST
    saved_streak, saved_last_day = db_get_dm_state(room)
    dm_streaks[room] = saved_streak
    dm_last_day[room] = saved_last_day

    if room not in dm_sent_today:
        dm_sent_today[room] = {sender_username: False, recipient_username: False}

    dm_sent_today[room][sender_username] = True

    both_sent = (
        dm_sent_today[room].get(sender_username, False)
        and dm_sent_today[room].get(recipient_username, False)
    )

    lit_up = False
    if both_sent and dm_last_day[room] != today:
        dm_streaks[room] += 1
        dm_last_day[room] = today
        lit_up = True

        dm_sent_today[room][sender_username] = False
        dm_sent_today[room][recipient_username] = False

    # ✅ persist current streak state EVERY message
    db_set_dm_state(room, dm_streaks[room], dm_last_day[room])

    # emit message + streak update
    payload = {
        "sender": sender_username,
        "recipient": recipient_username,
        "message": message_text,
        "timestamp": ts,
        "day_label": day_label,
    }

    completed_today = (dm_last_day.get(room) == today)

    emit("new_message", payload, room=room)
    emit(
        "streak_update",
        {
            "streak": dm_streaks[room],
            "completed_today": completed_today,
            "lit_up": lit_up,
        },
        room=room
    )


@app.route("/demo/reset_all")
def demo_reset_all():
    """
    Demo-only: wipes ALL messages (DM + community) and resets DM streak memory.
    Does NOT delete users/profiles.
    """
    conn = db_helper.get_connection()
    try:
        conn.execute("DELETE FROM messages")

        # ✅ ALSO clear persisted DM streak state
        conn.execute("DELETE FROM dm_streak_state")

        # safe reset of auto-increment (won't crash if sqlite_sequence missing)
        try:
            conn.execute("DELETE FROM sqlite_sequence WHERE name='messages'")
        except Exception:
            pass

        conn.commit()
    finally:
        conn.close()

    dm_streaks.clear()
    dm_sent_today.clear()
    dm_last_day.clear()

    session.pop("demo_date", None)

    return "✅ Reset done: messages cleared + DM streaks cleared + demo date cleared."


@app.route("/demo/set_date")
def demo_set_date():
    d = (request.args.get("date") or "").strip()
    if not d:
        return "Give ?date=YYYY-MM-DD", 400

    try:
        datetime.strptime(d, "%Y-%m-%d")
    except Exception:
        return "Invalid format. Use YYYY-MM-DD", 400

    session["demo_date"] = d
    return f"✅ Demo date set to {d}"


@app.route("/demo/set_streak")
def demo_set_streak():
    u1 = (request.args.get("u1") or "").strip()
    u2 = (request.args.get("u2") or "").strip()
    s  = (request.args.get("streak") or "0").strip()

    if not u1 or not u2:
        return "Need ?u1=...&u2=...", 400

    try:
        streak_val = int(s)
    except Exception:
        return "streak must be an integer", 400

    room = room_name(u1, u2)
    dm_streaks[room] = max(0, streak_val)

    now_dt = get_demo_now()
    yesterday = (now_dt.date() - timedelta(days=1)).strftime("%Y-%m-%d")
    dm_last_day[room] = yesterday

    dm_sent_today[room] = {u1: False, u2: False}

    # ✅ persist your manual set too
    db_set_dm_state(room, dm_streaks[room], dm_last_day[room])

    return f"✅ Set {room} streak={dm_streaks[room]} (last_day={yesterday})"


@app.route("/demo/day")
def demo_day():
    current = session.get("demo_date")

    if current:
        d = datetime.strptime(current, "%Y-%m-%d")
        d = d + timedelta(days=1)
    else:
        d = datetime.now() + timedelta(days=1)

    session["demo_date"] = d.strftime("%Y-%m-%d")
    return f"Demo date set to {session['demo_date']}"

# --- Yq ---
@app.route("/events_demo/set_date")
def events_demo_set_date():
    d = (request.args.get("date") or "").strip()
    if not d:
        return "Give ?date=YYYY-MM-DD", 400

    try:
        datetime.strptime(d, "%Y-%m-%d")
    except Exception:
        return "Invalid format. Use YYYY-MM-DD", 400

    session["events_demo_date"] = d
    return f"✅ Events demo date set to {d}"

@app.route("/events_demo/set_streak")
def events_demo_set_streak():
    if "user_id" not in session:
        return "Not logged in", 401

    s = (request.args.get("streak") or "").strip()

    try:
        streak_val = int(s)
    except Exception:
        return "streak must be integer", 400

    user_id = session["user_id"]

    # Use EVENTS demo date, not real date
    demo_today = get_events_demo_date_str()
    yesterday = (
        datetime.strptime(demo_today, "%Y-%m-%d") - timedelta(days=1)
    ).strftime("%Y-%m-%d")

    conn = db_helper.get_connection()
    try:
        # Ensure row exists (safe columns only)
        conn.execute("""
            INSERT OR IGNORE INTO user_streaks
            (user_id, daily_game_streak, winning_streak)
            VALUES (?, 0, 0)
        """, (user_id,))

        # ✅ USE last_play_date (matches DB)
        conn.execute("""
            UPDATE user_streaks
            SET daily_game_streak = ?,
                winning_streak = 0,
                last_play_date = ?,
                seed_claimed = 0
            WHERE user_id = ?
        """, (max(0, streak_val), yesterday, user_id))

        conn.commit()
    finally:
        conn.close()

    return f"✅ Events daily streak set to {streak_val}"


# --- Yq ---
queues = {"Elderly": [], "Youth": []}



# LEGACY_DUPLICATE_HANDLER (disabled to prevent double-processing)
# @socketio.on("flip_card")
# def flip_card(data):
#     room = data.get("room")
#     card_index = data.get("cardIndex")
#     role_in = (data.get("role") or "").strip().lower()
# 
#     role_map = {
#         "senior": "Elderly",
#         "elder": "Elderly",
#         "elderly": "Elderly",
#         "youth": "Youth",
#         "young": "Youth",
#     }
#     role = role_map.get(role_in, data.get("role"))
# 
#     if not room or card_index is None:
#         return
# 
#     emit("card_flipped", {
#         "cardIndex": card_index,
#         "role": role
#     }, room=room)
# 
# 
# 
# # Create queues for matching
# # Create queues for matching
waiting = {"Elderly": [], "Youth": []}
# 
# 
# 
# ===== ✅ Game state (reload / resync support) =====
# Server is the source of truth. Clients can request the latest state after reload.
memory_states = {}   # room_id -> state dict
hangman_states = {}  # room_id -> state dict

# ✅ NEW: Track players in each room for opponent name persistence
# room_id -> {"Elderly": {"user_id": int, "username": str}, "Youth": {...}}
room_players = {}




def cleanup_room(room, game_type):
    if game_type == "memory":
        memory_states.pop(room, None)
    elif game_type == "hangman":
        hangman_states.pop(room, None)
    # ✅ Clean up room players tracking
    room_players.pop(room, None)

def hash_room(s: str) -> int:
    h = 0
    for ch in (s or ""):
        h = ((h << 5) - h) + ord(ch)
        h &= 0xFFFFFFFF
    return abs(int(h))

def memory_default_state(room_id: str):
    symbols = ["🍎","🐶","🎈","🍪","🚗","🌸","⭐️","🍇","🕊️","⏰","⚽️","🎂"]
    deck = symbols + symbols
    rng = random.Random(hash_room(room_id))
    rng.shuffle(deck)
    start_turn = "Elderly" if (hash_room(room_id) % 2 == 0) else "Youth"
    return {
        "deck": deck,
        "matched": [],
        "scores": {"Elderly": 0, "Youth": 0},
        "current_turn": start_turn,
        "pairs_total": 12,
        "last_flip_role": None,
        "flipped": [],
        "game_over": False,
    }

def hangman_default_state(room_id: str):
    """
    ✅ FIXED: Uses truly random word selection instead of deterministic hash.
    Now each game will have a different word, even for the same two players.
    """
    words = [
        "APPLE", "HOUSE", "MUSIC", "RIVER", "CHAIR", "GARDEN", "KITCHEN", 
        "MOUNTAIN", "BICYCLE", "THUNDER", "DINOSAUR", "EGGPLANT", "FOUNTAIN", 
        "INGREDIENT", "LAUGH", "ALPHABET", "BUSINESS", "RAINDROP", "COMPUTER",
        "SUNLIGHT", "PENGUIN", "KEYBOARD", "BACKPACK", "STARFISH", "ELEPHANT",
        "VOLCANO", "BUTTERFLY", "SANDWICH", "TRAMPOLINE", "CHOCOLATE"
    ]
    # ✅ Use random.choice() for true randomization
    word = random.choice(words)
    
    # Randomly choose starting player (50/50 chance)
    start_turn = random.choice(["Elderly", "Youth"])
    
    print(f"🎲 HANGMAN: New game in room {room_id}")
    print(f"   Selected word: {word}")
    print(f"   Starting player: {start_turn}")
    
    return {
        "word": word,
        "guessed": [],
        "current_turn": start_turn,
        "game_over": False,
    }

def serialize_memory_state(state):
    return {
        "game_type": "memory",
        "deck": state.get("deck", []),
        "matched": list(state.get("matched", [])),
        "scores": state.get("scores", {"Elderly": 0, "Youth": 0}),
        "current_turn": state.get("current_turn", "Elderly"),
        "pairs_total": int(state.get("pairs_total", 12)),
        "flipped": list(state.get("flipped", [])),
        "game_over": bool(state.get("game_over", False)),
    }

def serialize_hangman_state(state):
    word = state.get("word", "")
    guessed = list(state.get("guessed", []))
    
    # Create display string showing guessed letters
    display = " ".join([ch if ch in guessed else "_" for ch in word])
    
    return {
        "game_type": "hangman",
        "guessed": guessed,
        "current_turn": state.get("current_turn", "Elderly"),
        "game_over": bool(state.get("game_over", False)),
        "word_display": display,  # ✅ Add this
        "word_length": len(word)   # ✅ Add this
    }

# ✅ FIXED: Fetch usernames from database during matchmaking
@socketio.on("join_waiting_room")
def handle_waiting_room(data):
    user_id = str(data.get("user_id"))
    role_in = (data.get("role") or "").strip().lower()
    game_in = (data.get("game_type") or "").strip().lower()

    role_map = {
        "senior": "Elderly",
        "elder": "Elderly",
        "elderly": "Elderly",
        "youth": "Youth",
        "young": "Youth",
    }
    role = role_map.get(role_in)

    game_map = {
        "memory": "memory",
        "memory-match": "memory",
        "memory_match": "memory",
        "hangman": "hangman",
    }
    game_type = game_map.get(game_in)

    # ✅ FIXED: Fetch username from database
    username = db_helper.get_username_by_id(user_id)
    if not username:
        username = "Player"  # Fallback

    print("\n=== JOIN_WAITING_ROOM ===")
    print("RAW:", data)
    print("SID:", request.sid)
    print("NORMALIZED:", user_id, username, role, game_type)

    if role not in waiting:
        emit("queue_error", {"message": f"Bad role: {role_in}"}, to=request.sid)
        return

    if game_type not in ("memory", "hangman"):
        emit("queue_error", {"message": f"Bad game: {game_in}"}, to=request.sid)
        return

    opponent_role = "Youth" if role == "Elderly" else "Elderly"

    # Find opponent in opposite queue with same game
    opponent_index = None
    for i, p in enumerate(waiting[opponent_role]):
        if p.get("game_type") == game_type:
            opponent_index = i
            break

    if opponent_index is not None:
        opponent = waiting[opponent_role].pop(opponent_index)
        # ✅ FIXED: Add timestamp to room ID to ensure unique rooms (and thus unique words)
        import time
        room_id = f"room_{opponent['user_id']}_{user_id}_{game_type}_{int(time.time())}"

        # ✅ FIXED: Get usernames (opponent already has username in queue)
        opponent_username = opponent.get("username", "Unknown")

        print("✅ MATCHED:", username, "("+role+")", "vs", opponent_username, "("+opponent_role+")", "ROOM:", room_id)
        
        room_players[room_id] = {
            role: {"user_id": user_id, "username": username},
            opponent_role: {"user_id": opponent["user_id"], "username": opponent_username}
        }

        
        join_room(room_id, sid=request.sid)
        join_room(room_id, sid=opponent["sid"])

        # ✅ FIXED: Send opponent usernames to both players
        emit("match_found", {
            "room": room_id,
            "your_role": role,
            "opponent_role": opponent_role,
            "opponent_username": opponent_username  # ← Critical fix
        }, to=request.sid)

        emit("match_found", {
            "room": room_id,
            "your_role": opponent_role,
            "opponent_role": role,
            "opponent_username": username  # ← Critical fix
        }, to=opponent["sid"])

    else:
        # ✅ FIXED: Store username in queue for when match is found
        waiting[role].append({
            "sid": request.sid, 
            "user_id": user_id, 
            "username": username,  # ← Store username
            "game_type": game_type
        })
        emit("queued", {"message": "Waiting for opponent..."}, to=request.sid)
        print("⏳ QUEUED:", username, role, game_type, "QUEUE SIZES:", {k: len(v) for k, v in waiting.items()})

def name_with_region(player: dict) -> str:
    if not player:
        return "Someone"
    uid = player.get("user_id")
    uname = player.get("username", "Someone")
    region = db_helper.get_user_region(uid) if uid else "Unknown"
    return f"<b>{uname}</b> ({region})"


@socketio.on("cancel_queue")
def cancel_queue(data):
    user_id = data.get("user_id")
    role = data.get("role")

    role_map = {"Senior": "Elderly", "Elder": "Elderly"}
    role = role_map.get(role, role)

    if role not in waiting:
        return

    waiting[role] = [p for p in waiting[role] if p.get("user_id") != user_id and p.get("sid") != request.sid]
    emit("queue_cancelled", {"message": "Left queue"}, to=request.sid)

@app.route("/events/waitingroom")
def waiting_room():
    if "user_id" not in session:
        return redirect(url_for("login"))

    game = request.args.get("game", "hangman")  # hangman or memory
    return render_template(
        "events/waitingroom.html",
        game_type=game,
        user_id=session["user_id"],
        role=session.get("role", "Youth")
    )


@socketio.on("flip_card")
def flip_card(data):
    """Memory Match: server-authoritative flips.
    - Player may flip only when it's their turn.
    - Turn only changes AFTER 2nd flip and ONLY on mismatch.
    - On match, same player keeps turn.
    """
    room = (data.get("room") or "").strip()
    idx = data.get("index")
    if idx is None:
        idx = data.get("cardIndex")
    if idx is None:
        idx = data.get("card_index")
    role_in = (data.get("role") or "").strip().lower()

    role_map = {
        "senior": "Elderly",
        "elder": "Elderly",
        "elderly": "Elderly",
        "youth": "Youth",
        "young": "Youth",
    }
    role = role_map.get(role_in, data.get("role")) or ""

    if not room:
        return
    if room not in memory_states:
        memory_states[room] = memory_default_state(room)

    state = memory_states[room]

    # If game already over, just resync
    if state.get("game_over"):
        emit("sync_state", serialize_memory_state(state), room=room)
        return

    # Validate idx
    try:
        idx = int(idx)
    except Exception:
        return

    deck = state.get("deck") or []
    if idx < 0 or idx >= len(deck):
        return

    # Enforce turn strictly
    if role and state.get("current_turn") and role != state.get("current_turn"):
        # Not your turn -> just resync you (and room) so UI stays correct
        emit("sync_state", serialize_memory_state(state), to=request.sid)
        return

    matched = set(state.get("matched") or [])
    flipped = list(state.get("flipped") or [])

    # Can't flip matched cards
    if idx in matched:
        return

    # Prevent flipping same card twice in a pair
    if idx in flipped:
        return

    # Only allow up to 2 flips before resolution
    if len(flipped) >= 2:
        return

    flipped.append(idx)
    state["flipped"] = flipped
    state["last_flip_role"] = role or state.get("current_turn")

    # After 1st flip: reveal to both, DO NOT change turn
    if len(flipped) == 1:
        emit("sync_state", serialize_memory_state(state), room=room)
        return
    
    # After 2nd flip, show both cards first here
    # emit("sync_state", serialize_memory_state(state), room=room)

    # After 2nd flip: resolve pair
    a, b = flipped[0], flipped[1]
    sym_a = deck[a]
    sym_b = deck[b]
    owner = state.get("last_flip_role") or role or state.get("current_turn")
    is_match = (sym_a == sym_b)
    #NEW: Emit sync_state BEFORE processing so both cards are visible
    # emit("sync_state", serialize_memory_state(state), room=room)

    if is_match:
        matched.update([a, b])
        state["matched"] = list(matched)
        scores = state.get("scores") or {}
        scores[owner] = int(scores.get(owner, 0)) + 1
        state["scores"] = scores
        # Keep turn on match
        next_turn = state.get("current_turn") or owner
    else:
        # Switch turn on mismatch
        curr = state.get("current_turn") or owner
        next_turn = "Youth" if curr == "Elderly" else "Elderly"
        state["current_turn"] = next_turn

    # Clear flipped after telling clients; clients will handle flip-back animation
    state["flipped"] = []
    state["last_flip_role"] = None

    # Game over?
    pairs_total = int(state.get("pairs_total", 0) or 0)
    total_scored = int((state.get("scores") or {}).get("Elderly", 0)) + int((state.get("scores") or {}).get("Youth", 0))
    if pairs_total and total_scored >= pairs_total:
        state["game_over"] = True

        scores = state.get("scores", {})
        e = int(scores.get("Elderly", 0))
        y = int(scores.get("Youth", 0))

        winner_role = None
        if e > y:
            winner_role = "Elderly"
        elif y > e:
            winner_role = "Youth"

        if winner_role:
            loser_role = "Youth" if winner_role == "Elderly" else "Elderly"

            winner = (room_players.get(room, {}).get(winner_role) or {})
            loser  = (room_players.get(room, {}).get(loser_role) or {})

            winner_region = db_helper.get_user_region(winner.get("user_id"))
            loser_region  = db_helper.get_user_region(loser.get("user_id"))

            winner_label = name_with_region(winner)
            loser_label  = name_with_region(loser)

            db_helper.add_notice(
                username=winner.get("username", "Someone"),
                region=winner_region,
                emoji="🏆",
                message=f"{winner_label} won Memory Match against {loser_label}!"
            )

            db_helper.add_notice(
                username=loser.get("username", "Someone"),
                region=loser_region,
                emoji="💔",
                message=f"{loser_label} lost Memory Match to {winner_label}."
            )
        else:
            # draw notice (optional)
            p1 = room_players.get(room, {}).get("Elderly") or {}
            p2 = room_players.get(room, {}).get("Youth") or {}

            p1_region = db_helper.get_user_region(p1.get("user_id"))
            p2_region = db_helper.get_user_region(p2.get("user_id"))

            p1_label = name_with_region(p1)
            p2_label = name_with_region(p2)

            db_helper.add_notice(
                username=p1.get("username","Someone"),
                region=p1_region,
                emoji="🤝",
                message=f"{p1_label} drew Memory Match with {p2_label}."
            )
            db_helper.add_notice(
                username=p2.get("username","Someone"),
                region=p2_region,
                emoji="🤝",
                message=f"{p2_label} drew Memory Match with {p1_label}."
            )


        cleanup_room(room, "memory")


    emit("pair_result", {
        "a": a,
        "b": b,
        "is_match": is_match,
        "next_turn": next_turn,
        "scores": state.get("scores", {}),
        "game_over": state.get("game_over", False),
    }, room=room)
    state["flipped"] = []
    # emit("sync_state", serialize_memory_state(state), room=room)


# ✅ FIXED: Send opponent name on join_game (for page reload)
@socketio.on("join_game")
def handle_join_game(data):
    room = (data.get("room") or "").strip()
    role = (data.get("role") or "").strip()
    game_type = (data.get("game_type") or "").strip().lower()

    if not room:
        return

    join_room(room)
    print("✅ join_game:", request.sid, "joined", room, "role:", role, "game_type:", game_type)

    # ✅ FIXED: Send opponent name when player joins/rejoins
    if room in room_players:
        opponent_role = "Youth" if role == "Elderly" else "Elderly"
        opponent_username = (room_players[room].get(opponent_role) or {}).get("username")


        if opponent_username:
            print(f"📤 Sending opponent name to {request.sid}: {opponent_username}")
            emit("opponent_info", {
                "opponent_username": opponent_username
            }, to=request.sid)
        else:
            print(f"⚠️ No opponent username found for role {opponent_role} in room {room}")

    # Ensure state exists for reload/resync
    if game_type == "memory":
        if room not in memory_states:
            memory_states[room] = memory_default_state(room)

    elif game_type == "hangman":
        if room not in hangman_states:
            hangman_states[room] = hangman_default_state(room)

    emit("player_joined", {"role": role}, room=room)

    # Send current state to the joining client
    if game_type == "memory" and room in memory_states:
        emit("sync_state", serialize_memory_state(memory_states[room]), to=request.sid)

    if game_type == "hangman" and room in hangman_states:
        emit("sync_state", serialize_hangman_state(hangman_states[room]), to=request.sid)


@socketio.on("request_state")
def handle_request_state(data):
    room = (data.get("room") or "").strip()
    game_type = (data.get("game_type") or "").strip().lower()
    if not room:
        return

    if game_type == "memory":
        if room not in memory_states:
            memory_states[room] = memory_default_state(room)
        emit("sync_state", serialize_memory_state(memory_states[room]), to=request.sid)

    elif game_type == "hangman":
        if room not in hangman_states:
            hangman_states[room] = hangman_default_state(room)
        emit("sync_state", serialize_hangman_state(hangman_states[room]), to=request.sid)


@socketio.on("submit_guess")
def handle_submit_guess(data):
    # Hangman guess (server-authoritative)
    room = (data.get("room") or "").strip()
    letter = (data.get("letter") or "").strip()
    role_in = (data.get("role") or "").strip().lower()

    role_map = {
        "senior": "Elderly",
        "elder": "Elderly",
        "elderly": "Elderly",
        "youth": "Youth",
        "young": "Youth",
    }
    role = role_map.get(role_in, data.get("role"))

    if not room or not letter or not role:
        return

    letter = letter[0].upper()

    if room not in hangman_states:
        hangman_states[room] = hangman_default_state(room)
    state = hangman_states[room]

    print(f"BEFORE - Current turn: {state.get('current_turn')}, Guesser: {role}, Letter: {letter}")

    if state.get("game_over"):
        return

    if role != state.get("current_turn"):
        print(f"REJECTED - Not {role}'s turn (current: {state.get('current_turn')})")
        return

    if letter in state.get("guessed", []):
        return

    state["guessed"].append(letter)

    correct = letter in state.get("word", "")
    print(f"Letter {letter} is {'CORRECT' if correct else 'WRONG'} (word: {state.get('word')})")
    
    # ✅ Switch turn ONLY if guess was wrong
    if not correct:
        old_turn = state["current_turn"]
        state["current_turn"] = "Youth" if state["current_turn"] == "Elderly" else "Elderly"
        print(f"TURN SWITCHED: {old_turn} -> {state['current_turn']}")
    else:
        print(f"CORRECT GUESS - Turn stays: {state['current_turn']}")

    # ✅ Check if game is won
    if all(ch in state["guessed"] for ch in state["word"]):
        state["game_over"] = True

        # ✅ winner/loser info from room_players
        winner_role = role
        loser_role = "Youth" if winner_role == "Elderly" else "Elderly"

        winner = (room_players.get(room, {}).get(winner_role) or {})
        loser  = (room_players.get(room, {}).get(loser_role) or {})

        winner_region = db_helper.get_user_region(winner.get("user_id"))
        loser_region  = db_helper.get_user_region(loser.get("user_id"))

        winner_label = name_with_region(winner)
        loser_label  = name_with_region(loser)

        # ✅ Winner region board
        db_helper.add_notice(
            username=winner.get("username", "Someone"),
            region=winner_region,
            emoji="🏆",
            message=f"{winner_label} won Hangman against {loser_label}!"
        )

        # ✅ Loser region board
        db_helper.add_notice(
            username=loser.get("username", "Someone"),
            region=loser_region,
            emoji="💔",
            message=f"{loser_label} lost Hangman to {winner_label}."
        )


        cleanup_room(room, "hangman")


    print(f"AFTER - Current turn: {state.get('current_turn')}")

    # ✅ Send complete game state to both clients
    # emit("game_update", {
    #     "letter": letter,
    #     "guesser_role": role,
    #     "correct": correct,
    #     "current_turn": state.get("current_turn"),
    #     "guessed": state.get("guessed", []),
    #     "game_over": state.get("game_over", False)
    # }, room=room)
    
    # print(f"EMITTED game_update with current_turn: {state.get('current_turn')}")
    emit("game_update", {
    "letter": letter,
    "guesser_role": role,
    "correct": correct,
    "current_turn": state.get("current_turn"),
    "guessed": state.get("guessed", []),
    "word_display": " ".join(
        ch if ch in state["guessed"] else "_" 
        for ch in state["word"]
    ),
    "game_over": state.get("game_over", False)
    }, room=room)

#Changed
@socketio.on("forfeit_game")
def handle_forfeit(data):
    """If a player leaves mid-game, the opponent instantly wins."""
    room = (data.get("room") or "").strip()
    game_type = (data.get("game_type") or "").strip().lower()
    role_in = (data.get("role") or "").strip().lower()

    role_map = {
        "senior": "Elderly",
        "elder": "Elderly",
        "elderly": "Elderly",
        "youth": "Youth",
        "young": "Youth",
    }
    leaver_role = role_map.get(role_in, data.get("role")) or ""

    if not room:
        return


    winner_role = "Youth" if leaver_role == "Elderly" else "Elderly"

    # Mark server state as game over so reload doesn't revive the match
    if game_type == "memory":
        if room in memory_states:
            memory_states[room]["game_over"] = True
    elif game_type == "hangman":
        if room in hangman_states:
            hangman_states[room]["game_over"] = True

    emit("opponent_forfeit", {
        "game_type": game_type,
        "winner_role": winner_role,
        "leaver_role": leaver_role
    }, room=room)

    cleanup_room(room, game_type)

# Don't delete this part 
if __name__ == "__main__":
    socketio.run(app, host="127.0.0.1", port=5000, debug=False, use_reloader=False)

def cleanup_room(room, game_type):
    if game_type == "memory":
        memory_states.pop(room, None)
    elif game_type == "hangman":
        hangman_states.pop(room, None)


from flask import Blueprint, render_template, session, redirect, url_for
from database import db_helper
from flask_socketio import join_room, emit
from datetime import datetime
from features.messaging import init_messaging
init_messaging(socketio)
messaging_bp = Blueprint(
    "messaging",
    __name__,
    url_prefix="/messages"
)



# ==============================
# 🔌 SocketIO Setup
# ==============================
def init_messaging(socketio):

    @socketio.on("join_room")
    def handle_join(data):
        user_id = data.get("user_id")
        other_id = data.get("other_id")

        if not user_id or not other_id:
            return

        room = f"chat_{min(user_id, other_id)}_{max(user_id, other_id)}"
        join_room(room)

    @socketio.on("send_message")
    def handle_send(data):
        sender_id = data.get("sender_id")
        receiver_id = data.get("receiver_id")
        content = data.get("content")

        if not sender_id or not receiver_id or not content:
            return

        room = f"chat_{min(sender_id, receiver_id)}_{max(sender_id, receiver_id)}"

        # Save message to DB
        db_helper.save_message(sender_id, receiver_id, content)

        emit(
            "receive_message",
            {
                "sender_id": sender_id,
                "content": content,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            room=room
        )