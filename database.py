import sqlite3
from datetime import datetime, timedelta
import random
import string
from werkzeug.security import generate_password_hash, check_password_hash
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "legacygarden.db")
class DatabaseHelper:
    def __init__(self, db_name='legacygarden.db'):
        self.db_name = db_name
        self.init_database()

    def get_connection(self):
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        DB_PATH = os.path.join(BASE_DIR, "legacygarden.db")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        # 1. CORE USER TABLES
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                role TEXT,
                points INTEGER DEFAULT 0
            )
        """)
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN points INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass



        # 2B. STORY DRAFTS (NEW)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS story_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT,
                content TEXT,
                topic TEXT,
                image_path TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        draft_alters = [
            "ALTER TABLE story_drafts ADD COLUMN image_path TEXT",
            "ALTER TABLE story_drafts ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE story_drafts ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
        ]
        for stmt in draft_alters:
            try:
                cursor.execute(stmt)
            except sqlite3.OperationalError:
                pass


        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                region TEXT,
                email TEXT,
                bio TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # --- SAFE ALTER: add profile_pic column if missing ---
        try:
            cursor.execute("ALTER TABLE profiles ADD COLUMN profile_pic TEXT")
        except sqlite3.OperationalError:
            pass

        # --- SAFE ALTER: add missing columns for profiles (settings + profile pic) ---
        profile_alters = [
            "ALTER TABLE profiles ADD COLUMN profile_pic TEXT",

            "ALTER TABLE profiles ADD COLUMN show_email INTEGER DEFAULT 1",
            "ALTER TABLE profiles ADD COLUMN show_region INTEGER DEFAULT 1",
            "ALTER TABLE profiles ADD COLUMN community_visible INTEGER DEFAULT 1",

            "ALTER TABLE profiles ADD COLUMN notify_messages INTEGER DEFAULT 1",
            "ALTER TABLE profiles ADD COLUMN notify_updates INTEGER DEFAULT 1",
            "ALTER TABLE profiles ADD COLUMN notify_events INTEGER DEFAULT 1",
            "ALTER TABLE profiles ADD COLUMN notify_comm INTEGER DEFAULT 1",
            "ALTER TABLE profiles ADD COLUMN notify_inapp INTEGER DEFAULT 1",
        ]

        for stmt in profile_alters:
            try:
                cursor.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists



        # 2. STORIES
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                content TEXT,
                topic TEXT,
                role_visibility TEXT,
                image_path TEXT,
                status TEXT DEFAULT 'approved',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        try:
            cursor.execute("ALTER TABLE stories ADD COLUMN topic TEXT")
        except sqlite3.OperationalError:
            pass
        # Likes & Comments
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS story_likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id INTEGER,
                user_id INTEGER,
                FOREIGN KEY(story_id) REFERENCES stories(id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                UNIQUE(story_id, user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS story_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id INTEGER,
                user_id INTEGER,
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(story_id) REFERENCES stories(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
CREATE TABLE IF NOT EXISTS inventory_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,              -- 'seed_tree' | 'seed_flower' | 'water' | 'points'
    delta INTEGER NOT NULL,          -- +10, -5, etc
    source TEXT NOT NULL,            -- 'Watered plant', 'Harvested tree', 'Streak reward', etc
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
)
""")
        
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS comment_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                comment_id INTEGER NOT NULL,
                reporter_user_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # --- SAFE ALTER: add missing columns for stories ---
        story_alters = [
            "ALTER TABLE stories ADD COLUMN image_path TEXT",
            "ALTER TABLE stories ADD COLUMN role_visibility TEXT",
            "ALTER TABLE stories ADD COLUMN topic TEXT",
            "ALTER TABLE stories ADD COLUMN status TEXT DEFAULT 'approved'",
            "ALTER TABLE stories ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
        ]

        for stmt in story_alters:
            try:
                cursor.execute(stmt)
            except sqlite3.OperationalError:
                pass
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id INTEGER,
                user_id INTEGER,
                reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(story_id) REFERENCES stories(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        
    
        # 3. GARDEN
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_inventory (
                user_id INTEGER PRIMARY KEY,
                seed_tree INTEGER DEFAULT 3,
                seed_flower INTEGER DEFAULT 3,
                water INTEGER DEFAULT 10,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plot_number INTEGER NOT NULL,
                plant_type TEXT,
                growth_stage INTEGER DEFAULT 0,
                last_watered_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                cost INTEGER NOT NULL,
                image_filename TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                reward_id INTEGER,
                redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_at TIMESTAMP,
                qr_code_filename TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (reward_id) REFERENCES rewards(id)
            )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS garden_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        category TEXT NOT NULL,      -- flower / tree / water / points
        title TEXT NOT NULL,         -- human readable message
        amount INTEGER DEFAULT 0,    -- + / - change (optional)
        created_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_garden_history_user_time
        ON garden_history(user_id, created_at)
        """)

        # Default Rewards
        if cursor.execute("SELECT count(*) FROM rewards").fetchone()[0] == 0:
            cursor.execute("INSERT INTO rewards (name, cost, image_filename) VALUES ('FairPrice $5 Voucher', 20, 'rewards_fairprice.jpg')")
            cursor.execute("INSERT INTO rewards (name, cost, image_filename) VALUES ('Shopee $5 Voucher', 25, 'rewards_shopee.jpg')")
            cursor.execute("INSERT INTO rewards (name, cost, image_filename) VALUES ('PopMart SG $5 Voucher', 30, 'rewards_popmart.jpg')")

        # 4. MESSAGING & COMMUNITY CHAT (Zhi Ni & Felicia's Modules) 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                receiver_id INTEGER,
                region_name TEXT, 
                message_text TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(sender_id) REFERENCES users(id)
            )
        """)


        # 5. NOTICES & EVENTS (Felicia & Yi Qian's Modules)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                message TEXT,
                region TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # --- SAFE ALTER: add emoji column to notices ---
        try:
            cursor.execute("ALTER TABLE notices ADD COLUMN emoji TEXT")
        except sqlite3.OperationalError:
            pass

        # --- SAFE ALTER: community guidelines acceptance (profiles) ---
        for stmt in [
            "ALTER TABLE profiles ADD COLUMN guidelines_accepted INTEGER DEFAULT 0",
            "ALTER TABLE profiles ADD COLUMN guidelines_accepted_at TEXT"
        ]:
            try:
                cursor.execute(stmt)
            except sqlite3.OperationalError:
                pass
            
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS weekly_achievements (
                week_start TEXT PRIMARY KEY,
                most_active_region TEXT,
                participation_region TEXT,
                best_harvest_region TEXT,
                generated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        for stmt in [
            "ALTER TABLE weekly_achievements ADD COLUMN best_harvest_region TEXT",
        ]:
            try:
                cursor.execute(stmt)
            except sqlite3.OperationalError:
                pass



        cursor.execute("""
        CREATE TABLE IF NOT EXISTS community_tree_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            region TEXT,
            action TEXT,              -- 'harvest_tree' or 'harvest_flower'
            points INTEGER DEFAULT 0,  -- 10 tree, 5 flower
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        # -- Added yq -- 
        cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        short_description TEXT,
        full_description TEXT,
        registration_start TEXT,
        registration_end TEXT,
        event_date TEXT,
        event_time TEXT,
        venue TEXT,
        image_filename TEXT,
        status TEXT DEFAULT 'approved',
        report_reason TEXT,
        created_by INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(created_by) REFERENCES users(id)
    )
    """)


        # 6. JUST ADDED EVENT YI QIAN 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_streaks (
                user_id INTEGER PRIMARY KEY,
                daily_game_streak INTEGER DEFAULT 0,
                winning_streak INTEGER DEFAULT 0,
                last_play_date TEXT,
                seed_claimed INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

         # --- Add weekly tracking columns (safe ALTER) ---
        for stmt in [
            "ALTER TABLE user_streaks ADD COLUMN week_start_date TEXT",
            "ALTER TABLE user_streaks ADD COLUMN last_reset_date TEXT"
        ]:
            try:
                cursor.execute(stmt)
            except sqlite3.OperationalError:
                pass

                # ✅ ADDED: Game History Table (tracks who played with whom)
        # This table records every game match between players
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player1_id INTEGER NOT NULL,
                player2_id INTEGER NOT NULL,
                game_type TEXT NOT NULL,
                winner_id INTEGER,
                played_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(player1_id) REFERENCES users(id),
                FOREIGN KEY(player2_id) REFERENCES users(id),
                FOREIGN KEY(winner_id) REFERENCES users(id)
            )
        """)

        # =========================
        # DEFAULT ADMIN ACCOUNT
        # =========================
        cursor.execute("SELECT * FROM users WHERE username = ?", ("winx_admin",))
        admin = cursor.fetchone()

        if not admin:
            hashed_pw = generate_password_hash("Password123")
            cursor.execute("""
                INSERT INTO users (username, password, role)
                VALUES (?, ?, ?)
            """, ("winx_admin", hashed_pw, "admin"))
            print("✅ winx_admin admin created.")
        else:
            # Force role to admin if already exists
            cursor.execute("""
                UPDATE users
                SET role = 'Admin'
                WHERE username = ?
            """, ("winx_admin",))

        # --- SAFE ALTER: add DM status columns + optional media fields ---
        msg_alters = [
            "ALTER TABLE messages ADD COLUMN message_type TEXT DEFAULT 'text'",
            "ALTER TABLE messages ADD COLUMN media_path TEXT",
            "ALTER TABLE messages ADD COLUMN audio_path TEXT",
            "ALTER TABLE messages ADD COLUMN file_name TEXT",
            "ALTER TABLE messages ADD COLUMN delivered_at TEXT",
            "ALTER TABLE messages ADD COLUMN read_at TEXT",
            
        ]
        for stmt in msg_alters:
            try:
                cursor.execute(stmt)
            except sqlite3.OperationalError:
                pass

        conn.commit()
        conn.close()
        print("Legacy Garden Database fully initialized for the whole team.")

    def get_user_by_login(self, login_input):
        conn = self.get_connection()
        try:
            # We need to find the user in 'users' OR their email in 'profiles'
            # We use a LEFT JOIN to see both tables at once
            query = """
                SELECT u.* FROM users u
                LEFT JOIN profiles p ON u.id = p.user_id
                WHERE u.username = ? OR p.email = ?
            """
            # We pass 'login_input' twice: once for username, once for email
            result = conn.execute(query, (login_input, login_input)).fetchone()
            return result
        finally:
            conn.close()

        # ✅ NEW HELPER FUNCTION: Get username by user_id
    def get_username_by_id(self, user_id):
        """
        Fetch username by user_id.
        Returns username string or None.
        """
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT username FROM users WHERE id = ?",
                (user_id,)
            ).fetchone()
            return row["username"] if row else None
        except Exception as e:
            print(f"❌ Error fetching username for user_id {user_id}: {e}")
            return None
        finally:
            conn.close()


    # fel added for community
    def get_profile_by_user_id(self, user_id):
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM profiles WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    def get_region_member_counts(self, region_name):
        conn = self.get_connection()
        try:
            # Count youth/senior based on users.role, filtered by profiles.region
            query = """
                SELECT
                    SUM(CASE WHEN LOWER(u.role) = 'youth' THEN 1 ELSE 0 END) AS youth_count,
                    SUM(CASE WHEN LOWER(u.role) = 'senior' THEN 1 ELSE 0 END) AS senior_count,
                    COUNT(*) AS total_count
                FROM users u
                JOIN profiles p ON u.id = p.user_id
                WHERE p.region = ?
            """
            row = conn.execute(query, (region_name,)).fetchone()

            youth = row["youth_count"] or 0
            senior = row["senior_count"] or 0
            total = row["total_count"] or 0
            return youth, senior, total
        finally:
            conn.close()

    def get_latest_notice_timestamp(self, region_name):
        """Return latest notice timestamp for a region (as datetime), or None."""
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT MAX(timestamp) AS last_ts FROM notices WHERE region = ?",
                (region_name,)
            ).fetchone()

            if not row or not row["last_ts"]:
                return None

            # SQLite CURRENT_TIMESTAMP usually returns 'YYYY-MM-DD HH:MM:SS'
            return datetime.strptime(row["last_ts"], "%Y-%m-%d %H:%M:%S")
        finally:
            conn.close()

    def get_region_notices(self, region_name, limit=10):
        conn = self.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id, username, message, region, emoji, timestamp
                FROM notices
                WHERE region = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (region_name, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_user_region(self, user_id):
        p = self.get_profile_by_user_id(user_id) or {}
        return p.get("region", "Unknown")




    def add_notice(self, username, region, message, emoji="ℹ️"):
        conn = self.get_connection()
        try:
            conn.execute(
                """
                INSERT INTO notices (username, message, region, emoji)
                VALUES (?, ?, ?, ?)
                """,
                (username, message, region, emoji)
            )
            conn.commit()
        finally:
            conn.close()


    def get_weekly_achievements(self, week_start: str):
        conn = self.get_connection()
        try:
            row = conn.execute("""
                SELECT week_start,
                    most_active_region,
                    participation_region,
                    best_harvest_region,
                    generated_at
                FROM weekly_achievements
                WHERE week_start = ?
            """, (week_start,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
            

    def get_latest_notice_timestamp_in_range(self, start_dt, end_dt):
        conn = self.get_connection()
        try:
            start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

            row = conn.execute("""
                SELECT MAX(timestamp) AS last_ts
                FROM notices
                WHERE timestamp >= ? AND timestamp < ?
            """, (start_str, end_str)).fetchone()

            if not row or not row["last_ts"]:
                return None

            return datetime.strptime(row["last_ts"], "%Y-%m-%d %H:%M:%S")
        finally:
            conn.close()

    def get_region_message_counts(self, start_dt: datetime, end_dt: datetime):
        """
        Counts COMMUNITY chat messages per region within [start_dt, end_dt).
        Community messages are those with receiver_id IS NULL.
        """
        start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

        conn = self.get_connection()
        try:
            rows = conn.execute("""
                SELECT region_name, COUNT(*) AS msg_count
                FROM messages
                WHERE receiver_id IS NULL
                AND region_name IS NOT NULL
                AND region_name != ''
                AND timestamp >= ?
                AND timestamp < ?
                GROUP BY region_name
            """, (start_str, end_str)).fetchall()

            return {r["region_name"]: int(r["msg_count"] or 0) for r in rows}
        finally:
            conn.close()


    def save_weekly_achievements(self, week_start, most_active, participation, best_harvest):
        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO weekly_achievements
                (week_start, most_active_region, participation_region, best_harvest_region, generated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (week_start, most_active, participation, best_harvest))
            conn.commit()
        finally:
            conn.close()



    def compute_weekly_winners(self, week_start_dt, week_end_dt):
        """
        Most Active Region = highest total activity count
        Participation Award = highest unique users count

        Activity sources:
        - stories
        - comments
        - game_history
        - community_tree_stats
        ✅ + community region chat messages (messages where receiver_id IS NULL)
        """
        ws = week_start_dt.strftime("%Y-%m-%d %H:%M:%S")
        we = week_end_dt.strftime("%Y-%m-%d %H:%M:%S")

        conn = self.get_connection()
        try:
            # ---------- MOST ACTIVE REGION (TOTAL ACTIONS) ----------
            row_active = conn.execute("""
                SELECT region, COUNT(*) AS total_actions
                FROM (
                    -- Stories posted
                    SELECT p.region AS region, s.user_id AS user_id
                    FROM stories s
                    JOIN profiles p ON p.user_id = s.user_id
                    WHERE s.created_at >= ? AND s.created_at < ?
                    AND s.status = 'approved'

                    UNION ALL

                    -- Comments made
                    SELECT p.region AS region, c.user_id AS user_id
                    FROM story_comments c
                    JOIN profiles p ON p.user_id = c.user_id
                    WHERE c.created_at >= ? AND c.created_at < ?

                    UNION ALL

                    -- Games played (count each match as 1 action per player)
                    SELECT p1.region AS region, gh.player1_id AS user_id
                    FROM game_history gh
                    JOIN profiles p1 ON p1.user_id = gh.player1_id
                    WHERE gh.played_at >= ? AND gh.played_at < ?

                    UNION ALL

                    SELECT p2.region AS region, gh.player2_id AS user_id
                    FROM game_history gh
                    JOIN profiles p2 ON p2.user_id = gh.player2_id
                    WHERE gh.played_at >= ? AND gh.played_at < ?

                    UNION ALL

                    -- Garden harvest stats (tree/flower)
                    SELECT cts.region AS region, cts.user_id AS user_id
                    FROM community_tree_stats cts
                    WHERE cts.created_at >= ? AND cts.created_at < ?

                    UNION ALL

                    -- ✅ Community messages (region chat)
                    SELECT m.region_name AS region, m.sender_id AS user_id
                    FROM messages m
                    WHERE m.receiver_id IS NULL
                    AND m.timestamp >= ? AND m.timestamp < ?
                )
                WHERE region IS NOT NULL AND region != ''
                GROUP BY region
                ORDER BY total_actions DESC
                LIMIT 1
            """, (ws, we, ws, we, ws, we, ws, we, ws, we, ws, we)).fetchone()

            most_active = (row_active["region"] + " Region") if row_active else "—"

            # ---------- PARTICIPATION AWARD (UNIQUE USERS) ----------
            row_participation = conn.execute("""
                SELECT region, COUNT(DISTINCT user_id) AS unique_users
                FROM (
                    SELECT p.region AS region, s.user_id AS user_id
                    FROM stories s
                    JOIN profiles p ON p.user_id = s.user_id
                    WHERE s.created_at >= ? AND s.created_at < ?
                    AND s.status = 'approved'

                    UNION

                    SELECT p.region AS region, c.user_id AS user_id
                    FROM story_comments c
                    JOIN profiles p ON p.user_id = c.user_id
                    WHERE c.created_at >= ? AND c.created_at < ?

                    UNION

                    SELECT p1.region AS region, gh.player1_id AS user_id
                    FROM game_history gh
                    JOIN profiles p1 ON p1.user_id = gh.player1_id
                    WHERE gh.played_at >= ? AND gh.played_at < ?

                    UNION

                    SELECT p2.region AS region, gh.player2_id AS user_id
                    FROM game_history gh
                    JOIN profiles p2 ON p2.user_id = gh.player2_id
                    WHERE gh.played_at >= ? AND gh.played_at < ?

                    UNION

                    SELECT cts.region AS region, cts.user_id AS user_id
                    FROM community_tree_stats cts
                    WHERE cts.created_at >= ? AND cts.created_at < ?

                    UNION

                    -- ✅ Community messages (unique senders in region chat)
                    SELECT m.region_name AS region, m.sender_id AS user_id
                    FROM messages m
                    WHERE m.receiver_id IS NULL
                    AND m.timestamp >= ? AND m.timestamp < ?
                )
                WHERE region IS NOT NULL AND region != ''
                GROUP BY region
                ORDER BY unique_users DESC
                LIMIT 1
            """, (ws, we, ws, we, ws, we, ws, we, ws, we, ws, we)).fetchone()

            participation = (row_participation["region"] + " Region") if row_participation else "—"

            # ---------- BEST HARVEST REGION ----------
            row_harvest = conn.execute("""
                SELECT region, COUNT(*) AS harvest_actions
                FROM community_tree_stats
                WHERE created_at >= ? AND created_at < ?
                AND action IN ('harvest_tree', 'harvest_flower')
                GROUP BY region
                ORDER BY harvest_actions DESC
                LIMIT 1
            """, (ws, we)).fetchone()

            best_harvest = (row_harvest["region"] + " Region") if row_harvest else "—"

            # If you still want best flower region:
            row_flower = conn.execute("""
                SELECT region, COUNT(*) AS flower_actions
                FROM community_tree_stats
                WHERE created_at >= ? AND created_at < ?
                AND action = 'harvest_flower'
                GROUP BY region
                ORDER BY flower_actions DESC
                LIMIT 1
            """, (ws, we)).fetchone()



            return most_active, participation, best_harvest

        finally:
            conn.close()




    def add_tree_stat(self, user_id, region, action, points):
        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT INTO community_tree_stats (user_id, region, action, points)
                VALUES (?, ?, ?, ?)
            """, (user_id, region, action, int(points or 0)))
            conn.commit()
        finally:
            conn.close()

    def get_region_tree_totals(self, region_name):
        conn = self.get_connection()
        try:
            row = conn.execute("""
                SELECT
                SUM(CASE WHEN action='harvest_tree' THEN 1 ELSE 0 END) AS trees,
                SUM(CASE WHEN action='harvest_flower' THEN 1 ELSE 0 END) AS flowers,
                SUM(COALESCE(points,0)) AS points
                FROM community_tree_stats
                WHERE region = ?
            """, (region_name,)).fetchone()

            return int(row["trees"] or 0), int(row["flowers"] or 0), int(row["points"] or 0)
        finally:
            conn.close()

    



    # yq added for event
    def get_or_create_user_streaks(self, user_id):
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM user_streaks WHERE user_id = ?",
                (user_id,)
            ).fetchone()

            if not row:
                # ✅ NEW: Set week_start_date when creating new user
                today = datetime.now()
                current_week_monday = self._week_start(today.strftime("%Y-%m-%d"))
                
                conn.execute("""
                    INSERT INTO user_streaks 
                    (user_id, daily_game_streak, winning_streak, last_play_date, seed_claimed, week_start_date, last_reset_date) 
                    VALUES (?, 0, 0, NULL, 0, ?, ?)
                """, (user_id, current_week_monday, today.strftime("%Y-%m-%d")))

                conn.commit()
                row = conn.execute(
                    "SELECT * FROM user_streaks WHERE user_id = ?",
                    (user_id,)
                ).fetchone()

            return dict(row)
        finally:
            conn.close()


    def update_streaks_on_game_end(self, user_id, did_win: bool):
        """
        Rules:
        - daily_game_streak +1 only once per day (if last_play_date != today)
        - winning_streak +1 if win, else reset to 0
        """
        conn = self.get_connection()
        try:
            today = datetime.now().strftime("%Y-%m-%d")

            s = self.get_or_create_user_streaks(user_id)
            daily = int(s.get("daily_game_streak") or 0)
            win = int(s.get("winning_streak") or 0)
            last_play = s.get("last_play_date")

            # daily streak only once/day
            if last_play != today:
                daily += 1
                last_play = today

            # winning streak
            if did_win:
                win += 1
            else:
                win = 0

            conn.execute("""
                UPDATE user_streaks
                SET daily_game_streak = ?, winning_streak = ?, last_play_date = ?
                WHERE user_id = ?
            """, (daily, win, last_play, user_id))
            conn.commit()

            return {"daily_game_streak": daily, "winning_streak": win}
        finally:
            conn.close()
# Added
    def decrement_daily_game_streak(self, user_id):
        """Decrease daily game streak by 1 (penalty for quitting mid-game)"""
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT daily_game_streak FROM user_streaks WHERE user_id = ?",
                (user_id,)
            ).fetchone()

            if row:
                current_streak = int(row["daily_game_streak"] or 0)
                new_streak = max(0, current_streak - 1)

                conn.execute(
                    "UPDATE user_streaks SET daily_game_streak = ? WHERE user_id = ?",
                    (new_streak, user_id)
                )
                conn.commit()
                print(f"✅ Daily streak decremented: {current_streak} -> {new_streak}")
            else:
                print(f"⚠️ No streak record found for user {user_id}")
        finally:
            conn.close()
        def claim_seed_reward(self, user_id):
            conn = self.get_connection()
            try:
                s = self.get_or_create_user_streaks(user_id)

                daily = int(s.get("daily_game_streak") or 0)
                claimed = int(s.get("seed_claimed") or 0)

                # Only allow claim when daily streak >= 5 and not claimed
                if daily < 5:
                    return {
                        "ok": False,
                        "message": "Need 5-day streak to claim.",
                        "daily_game_streak": daily,
                        "seed_claimed": claimed
                    }

                if claimed == 1:
                    return {
                        "ok": False,
                        "message": "Already claimed.",
                        "daily_game_streak": daily,
                        "seed_claimed": claimed
                    }

                # Mark seed as claimed
                conn.execute("""
                    UPDATE user_streaks
                    SET seed_claimed = 1
                    WHERE user_id = ?
                """, (user_id,))

                # ✅ ADD SEED TO INVENTORY
                conn.execute("""
                    UPDATE user_inventory
                    SET seed_tree = seed_tree + 1
                    WHERE user_id = ?
                """, (user_id,))

                conn.commit()

                return {
                    "ok": True,
                    "message": "Seed claimed!",
                    "daily_game_streak": daily,
                    "seed_claimed": 1
                }

            finally:
                conn.close()



    # Create one function to get "today" (real date OR test date)
    def _get_today_str(self, debug_date: str | None = None):
        """
        Returns YYYY-MM-DD.
        If debug_date is given (YYYY-MM-DD), uses that instead of system date.
        """
        if debug_date:
            return debug_date
        return datetime.now().strftime("%Y-%m-%d")
    
    # Weekly reset logic (Mon-based)
    def _week_start(self, date_str: str):
        d = datetime.strptime(date_str, "%Y-%m-%d")
        monday = d - timedelta(days=d.weekday())  # Monday
        return monday.strftime("%Y-%m-%d")
    
    def ensure_weekly_reset(self, user_id, today_str: str):
        """
        Reset daily_game_streak and seed_claimed every Monday at 12 AM.
        Winning streak is NOT reset weekly (only on loss).
        
        Returns:
            True if reset was performed, False otherwise
        """
        conn = self.get_connection()
        try:
            # Ensure user has a streak record
            self.get_or_create_user_streaks(user_id)

            # Get current week's Monday (YYYY-MM-DD)
            current_week_monday = self._week_start(today_str)

            # Get user's stored week_start_date
            row = conn.execute(
                "SELECT week_start_date FROM user_streaks WHERE user_id = ?",
                (user_id,)
            ).fetchone()

            stored_week = row["week_start_date"]

            # ✅ Handle first-time users (NULL week_start_date)
            if stored_week is None:
                # First time - just set the week, don't reset
                conn.execute("""
                    UPDATE user_streaks
                    SET week_start_date = ?,
                        last_reset_date = ?
                    WHERE user_id = ?
                """, (current_week_monday, today_str, user_id))
                conn.commit()
                return False  # No reset performed

            # ✅ Check if we've crossed into a new week
            if stored_week != current_week_monday:
                print(f"🔄 Weekly reset for user {user_id}: {stored_week} → {current_week_monday}")
                
                # ✅ CRITICAL: Reset ONLY daily_game_streak and seed_claimed
                # Do NOT reset winning_streak (that resets on loss only)
                conn.execute("""
                    UPDATE user_streaks
                    SET daily_game_streak = 0,
                        seed_claimed = 0,
                        last_play_date = NULL,
                        week_start_date = ?,
                        last_reset_date = ?
                    WHERE user_id = ?
                """, (current_week_monday, today_str, user_id))
                conn.commit()
                
                return True  # Reset was performed

            return False  # No reset needed
        finally:
            conn.close()

    def get_all_events(self):
        conn = self.get_connection()
        try:
            rows = conn.execute("""
                SELECT * FROM events
                ORDER BY created_at DESC
            """).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# added vivion
    def ensure_columns_exist(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        cols = [r['name'] for r in cursor.fetchall()]
        if 'points' not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN points INTEGER DEFAULT 0")
        
        cursor.execute("PRAGMA table_info(stories)")
        story_cols = [r['name'] for r in cursor.fetchall()]
        if 'status' not in story_cols:
            cursor.execute("ALTER TABLE stories ADD COLUMN status TEXT DEFAULT 'approved'")
        conn.commit()
        conn.close()
    def report_story(self, story_id, user_id, reason):
            conn = self.get_connection()
            try:
                # 1. Save the report record
                conn.execute("INSERT INTO reports (story_id, user_id, reason) VALUES (?,?,?)", 
                            (story_id, user_id, reason))
                
                # 2. HIDE THE STORY (Set status to 'pending')
                # This removes it from the public feed immediately.
                conn.execute("UPDATE stories SET status = 'pending' WHERE id = ?", (story_id,))
                
                conn.commit()
                print(f"⚠️ Story {story_id} reported by User {user_id}. Status -> Pending.")
                return True
            except Exception as e:
                print(f"❌ Error reporting story: {e}")
                return False
            finally:
                conn.close()
    # --- HELPERS ---
    def get_user_by_id(self, uid):
        conn = self.get_connection()
        u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        conn.close()
        return u

    def get_stories_for_pov(self, my_role, my_uid):
        conn = self.get_connection()

        my_role = (my_role or "").strip().lower()

        s = conn.execute("""
            SELECT s.*, u.username, u.role
            FROM stories s
            JOIN users u ON s.user_id = u.id
            WHERE (TRIM(LOWER(u.role)) != ? OR s.user_id = ?)
            AND s.status = 'approved'
            ORDER BY s.created_at DESC
        """, (my_role, my_uid)).fetchall()

        conn.close()
        return [dict(r) for r in s]

    def log_garden_history(self, user_id, category, title, amount=0):
            conn = self.get_connection()
            try:
                conn.execute(
                    "INSERT INTO garden_history (user_id, category, title, amount) VALUES (?, ?, ?, ?)",
                    (int(user_id), str(category), str(title), int(amount or 0))
                )
                conn.commit()
            finally:
                conn.close()

    # ✅ Fetch history
    def get_garden_history(self, user_id, category=None, limit=100):
        conn = self.get_connection()
        try:
            if category:
                rows = conn.execute("""
                    SELECT id, category, title, amount, created_at
                    FROM garden_history
                    WHERE user_id = ? AND category = ?
                    ORDER BY id DESC
                    LIMIT ?
                """, (int(user_id), str(category), int(limit))).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, category, title, amount, created_at
                    FROM garden_history
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                """, (int(user_id), int(limit))).fetchall()

            return [dict(r) for r in rows]
        finally:
            conn.close()


    # ✅ THIS WAS MISSING - NEEDED FOR MANAGE PAGE
    def get_user_stories(self, uid):
        conn = self.get_connection()
        s = conn.execute("""
            SELECT * FROM stories WHERE user_id=? ORDER BY created_at DESC
        """, (uid,)).fetchall()
        conn.close()
        return [dict(r) for r in s]

    def get_story_by_id(self, story_id):
        conn = self.get_connection()
        # Join with users to get username
        s = conn.execute("""
            SELECT s.*, u.username 
            FROM stories s
            JOIN users u ON s.user_id = u.id
            WHERE s.id=?
        """, (story_id,)).fetchone()
        conn.close()
        return s

    def get_story_comments(self, story_id):
        conn = self.get_connection()
        rows = conn.execute("""
            SELECT
                sc.id,
                sc.story_id,
                sc.user_id,         
                sc.content,
                sc.created_at,
                u.username
            FROM story_comments sc
            JOIN users u ON u.id = sc.user_id
            WHERE sc.story_id = ?
            ORDER BY sc.id DESC
        """, (story_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_comment(self, comment_id, requester_user_id):
        conn = self.get_connection()
        try:
            row = conn.execute("""
                SELECT sc.user_id AS comment_owner_id, s.user_id AS story_owner_id
                FROM story_comments sc
                JOIN stories s ON s.id = sc.story_id
                WHERE sc.id = ?
            """, (comment_id,)).fetchone()

            if not row:
                return False

            requester_user_id = int(requester_user_id)
            comment_owner_id = int(row["comment_owner_id"])
            story_owner_id = int(row["story_owner_id"])

            # ✅ allow comment owner OR story owner
            if requester_user_id not in (comment_owner_id, story_owner_id):
                return False

            conn.execute("DELETE FROM story_comments WHERE id = ?", (comment_id,))
            conn.commit()
            return True
        finally:
            conn.close()



    def report_comment(self, comment_id, reporter_user_id, reason):
        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT INTO comment_reports (comment_id, reporter_user_id, reason)
                VALUES (?, ?, ?)
            """, (comment_id, reporter_user_id, reason))
            conn.commit()
            return True
        except Exception as e:
            print("report_comment error:", e)
            return False
        finally:
            conn.close()

    def create_story(self, uid, title, content, topic, role, img, status='approved'):
        conn = self.get_connection()
        conn.execute("""
            INSERT INTO stories (user_id, title, content, topic, role_visibility, image_path, status)
            VALUES (?,?,?,?,?,?,?)
        """, (uid, title, content, topic, role, img, status))
        conn.commit()
        conn.close()

    def add_water_reward(self, uid, amt=1):
        conn = self.get_connection()
        conn.execute("INSERT OR IGNORE INTO user_inventory (user_id) VALUES (?)", (uid,))
        conn.execute("UPDATE user_inventory SET water = water + ? WHERE user_id = ?", (amt, uid))
        conn.commit()
        conn.close()

    # --- GARDEN LOGIC ---
    def get_user_inventory(self, uid):
        conn = self.get_connection()
        conn.execute("INSERT OR IGNORE INTO user_inventory (user_id) VALUES (?)", (uid,))
        conn.commit()
        inv = conn.execute("SELECT * FROM user_inventory WHERE user_id=?", (uid,)).fetchone()
        conn.close()
        return inv

    def get_user_plots(self, uid):
        conn = self.get_connection()
        for i in range(1, 4):
            conn.execute("""
                INSERT OR IGNORE INTO plots (user_id, plot_number, growth_stage)
                SELECT ?, ?, 0
                WHERE NOT EXISTS (SELECT 1 FROM plots WHERE user_id=? AND plot_number=?)
            """, (uid, i, uid, i))
        conn.commit()
        p = conn.execute("SELECT * FROM plots WHERE user_id=? ORDER BY plot_number", (uid,)).fetchall()
        conn.close()
        return p

    def plant_seed(self, uid, pid, type):
        conn = self.get_connection()
        inv = conn.execute("SELECT * FROM user_inventory WHERE user_id=?", (uid,)).fetchone()
        col = f"seed_{type}"
        if inv and inv[col] > 0:
            conn.execute(f"UPDATE user_inventory SET {col} = {col} - 1 WHERE user_id=?", (uid,))
            conn.execute("UPDATE plots SET plant_type=?, growth_stage=1 WHERE id=? AND user_id=?", (type, pid, uid))
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False

    def water_plant(self, uid, pid):
        conn = self.get_connection()
        inv = conn.execute("SELECT * FROM user_inventory WHERE user_id=?", (uid,)).fetchone()
        plot = conn.execute("SELECT * FROM plots WHERE id=?", (pid,)).fetchone()
        if inv and inv['water'] > 0 and plot['growth_stage'] < 3:
            conn.execute("UPDATE user_inventory SET water = water - 1 WHERE user_id=?", (uid,))
            conn.execute("UPDATE plots SET growth_stage = growth_stage + 1 WHERE id=?", (pid,))
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False

    def harvest_plant(self, uid, pid):
        conn = self.get_connection()
        plot = conn.execute("SELECT * FROM plots WHERE id=?", (pid,)).fetchone()
        if plot and plot['growth_stage'] == 3:
            pts = 10 if plot['plant_type'] == 'tree' else 25
            conn.execute("UPDATE users SET points = points + ? WHERE id=?", (pts, uid))
            conn.execute("UPDATE plots SET plant_type=NULL, growth_stage=0 WHERE id=?", (pid,))
            if random.random() > 0.5:
                col = f"seed_{plot['plant_type']}"
                conn.execute(f"UPDATE user_inventory SET {col} = {col} + 1 WHERE user_id=?", (uid,))
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False

    def get_all_rewards(self):
        conn = self.get_connection()
        r = conn.execute("SELECT * FROM rewards").fetchall()
        conn.close()
        return r

    def get_user_rewards(self, uid):
        conn = self.get_connection()
    
        r = conn.execute("""
            SELECT ur.*, r.name, r.image_filename, r.cost
            FROM user_rewards ur
            JOIN rewards r ON ur.reward_id=r.id
            WHERE ur.user_id=?
            ORDER BY (ur.used_at IS NOT NULL) ASC, ur.redeemed_at DESC
        """, (uid,)).fetchall()
        conn.close()
        return [dict(row) for row in r]

    def redeem_reward(self, uid, rid):
        conn = self.get_connection()
        u = self.get_user_by_id(uid)
        r = conn.execute("SELECT * FROM rewards WHERE id=?", (rid,)).fetchone()

        if u and r and u["points"] >= r["cost"]:
            # deduct points
            conn.execute("UPDATE users SET points = points - ? WHERE id=?", (r["cost"], uid))

            # save reward
            qr = "".join(random.choices(string.ascii_uppercase, k=10))
            conn.execute(
                "INSERT INTO user_rewards (user_id, reward_id, qr_code_filename) VALUES (?,?,?)",
                (uid, rid, qr),
            )

            conn.commit()
            conn.close()

            # ✅ LOG points spend in history
            self.log_garden_history(
                uid,
                "points",
                f"Redeemed {r['name']}",
                -int(r["cost"]),
            )

            return True

        conn.close()
        return False

    def use_reward(self, uid, urid):
        conn = self.get_connection()
        conn.execute("UPDATE user_rewards SET used_at=CURRENT_TIMESTAMP WHERE id=?", (urid,))
        conn.commit()
        conn.close()

    # 1. Update Default Inventory (Give 1 Seed Only)
    # inside init_database() where you reset stats:
    def reset_garden_stats(self, uid):
        conn = self.get_connection()
        conn.execute("UPDATE users SET points = 0 WHERE id = ?", (uid,))
        conn.execute("UPDATE user_inventory SET seed_tree=1, seed_flower=1, water=10 WHERE user_id=?", (uid,)) 
        conn.execute("UPDATE plots SET plant_type=NULL, growth_stage=0 WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM user_rewards WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()

    # 2. Update Watering Logic (Cost 5, Custom Stages)
    def water_plant(self, uid, pid):
        conn = self.get_connection()
        inv = conn.execute("SELECT * FROM user_inventory WHERE user_id=?", (uid,)).fetchone()
        plot = conn.execute("SELECT * FROM plots WHERE id=?", (pid,)).fetchone()
        
        if not inv or not plot: 
            conn.close(); return False


        COST_PER_STAGE = 5
        
    
        max_stage = 3 if plot['plant_type'] == 'tree' else 4

        if inv['water'] >= COST_PER_STAGE and plot['growth_stage'] < max_stage:
            conn.execute("UPDATE user_inventory SET water = water - ? WHERE user_id=?", (COST_PER_STAGE, uid))
            conn.execute("UPDATE plots SET growth_stage = growth_stage + 1 WHERE id=?", (pid,))
            conn.commit()
            conn.close()
            return True
        
        conn.close()
        return False

    # 3. Update Harvest Logic (Points Only, No Seeds)
    def harvest_plant(self, uid, pid):
        conn = self.get_connection()
        plot = conn.execute("SELECT * FROM plots WHERE id=?", (pid,)).fetchone()
        
        # Determine max stage again to ensure it's ready
        max_stage = 2 if plot and plot['plant_type'] == 'tree' else 3

        if plot and plot['growth_stage'] >= max_stage:

            pts = 10 if plot['plant_type'] == 'tree' else 25
            conn.execute("UPDATE users SET points = points + ? WHERE id=?", (pts, uid))

            conn.execute("UPDATE plots SET plant_type=NULL, growth_stage=0 WHERE id=?", (pid,))
            
            
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False
    
    def add_comment(self, story_id, user_id, content):
        conn = self.get_connection()
        try:
            conn.execute("INSERT INTO story_comments (story_id, user_id, content) VALUES (?,?,?)", 
                         (story_id, user_id, content))
            # Optional: Add points for commenting?
            # conn.execute("UPDATE stories SET comment_count = comment_count + 1 WHERE id=?", (story_id,))
            conn.commit()
        except Exception as e:
            print(f"Error adding comment: {e}")
        finally:
            conn.close()

    def delete_story(self, story_id):
        conn = None
        try:
            # USE THIS EXACT LINE: Your file calls it get_connection()
            conn = self.get_connection() 
            cursor = conn.cursor()
            
            # 1. Delete comments first (to avoid database errors)
            cursor.execute("DELETE FROM story_comments WHERE story_id = ?", (story_id,))

            # 2. Delete the story
            cursor.execute("DELETE FROM stories WHERE id = ?", (story_id,))
            
            conn.commit()
            print(f"✅ Story {story_id} deleted successfully.")
            return True
        except Exception as e:
            print(f"❌ Error deleting story: {e}")
            return False
        finally:
            if conn:
                conn.close()
    

    
    # ==========================================
    # ADMIN DASHBOARD FUNCTIONS
    # ==========================================
    def get_admin_stories(self):
        """
        Fetches stories that are 'pending' or 'reported' for the admin to review.
        """
        conn = self.get_connection()
        try:
            # We join with users to get the author's name
            # We subquery to get the report reason if it exists
            stories = conn.execute("""
                SELECT s.*, u.username, 
                       (SELECT reason FROM reports WHERE story_id = s.id LIMIT 1) as report_reason
                FROM stories s
                JOIN users u ON s.user_id = u.id
                WHERE s.status IN ('pending', 'reported')
                ORDER BY s.created_at DESC
            """).fetchall()
            return [dict(s) for s in stories]
        except Exception as e:
            print(f"❌ Error getting admin stories: {e}")
            return []
        finally:
            conn.close()

    def approve_story(self, story_id):
        """
        Sets a story's status to 'approved' so it appears on the home feed.
        """
        conn = self.get_connection()
        try:
            conn.execute("UPDATE stories SET status = 'approved' WHERE id = ?", (story_id,))
            conn.commit()
            print(f"✅ Story {story_id} approved.")
            return True
        except Exception as e:
            print(f"❌ Error approving story: {e}")
            return False
        finally:
            conn.close()


    def approve_story(self, story_id):
        conn = self.get_connection()
        try:
            conn.execute("UPDATE stories SET status = 'approved' WHERE id = ?", (story_id,))
            conn.commit()
            print(f"✅ Story {story_id} Approved!")
            return True
        except Exception as e:
            print(f"❌ Error approving story: {e}")
            return False
        finally:
            conn.close()


    # =========================
    # DRAFTS (DB-BASED)
    # =========================

    def create_draft(self, user_id, title="", content="", topic="", image_path=None):
        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT INTO story_drafts (user_id, title, content, topic, image_path, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (user_id, title, content, topic, image_path))
            conn.commit()
        finally:
            conn.close()

    def get_user_drafts(self, user_id):
        conn = self.get_connection()
        try:
            rows = conn.execute("""
                SELECT * FROM story_drafts
                WHERE user_id = ?
                ORDER BY updated_at DESC
            """, (user_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_draft_by_id(self, draft_id):
        conn = self.get_connection()
        try:
            row = conn.execute("SELECT * FROM story_drafts WHERE id = ?", (draft_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_draft(self, draft_id, user_id, title="", content="", topic="", image_path=None):
        conn = self.get_connection()
        try:
            conn.execute("""
                UPDATE story_drafts
                SET title = ?, content = ?, topic = ?, image_path = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
            """, (title, content, topic, image_path, draft_id, user_id))
            conn.commit()
            return True
        finally:
            conn.close()

    def delete_draft(self, draft_id, user_id):
        conn = self.get_connection()
        try:
            conn.execute("DELETE FROM story_drafts WHERE id = ? AND user_id = ?", (draft_id, user_id))
            conn.commit()
            return True
        finally:
            conn.close()

    def get_stories_for_pov(self, my_role, my_uid):
        conn = self.get_connection()
        # Add a subquery to check if the specific logged-in user liked each story
        s = conn.execute("""
            SELECT s.*, u.username, u.role,
                (SELECT COUNT(*) FROM story_likes WHERE story_id = s.id) as like_count,
                (SELECT COUNT(*) FROM story_comments WHERE story_id = s.id) as comment_count,
                (SELECT COUNT(*) FROM story_likes WHERE story_id = s.id AND user_id = ?) as is_liked_by_me
            FROM stories s
            JOIN users u ON s.user_id = u.id
            WHERE (TRIM(LOWER(u.role)) != ? OR s.user_id = ?)
            AND s.status = 'approved'
            ORDER BY s.created_at DESC
        """, (my_uid, my_role, my_uid)).fetchall()
        conn.close()
        return [dict(r) for r in s]
    
     # ✅ ADDED: Game History Helper Methods
    # These methods track and retrieve game match history between players
    
    def record_game_match(self, player1_id, player2_id, game_type, winner_id=None):
        """
        Record a completed game match between two players.
        winner_id can be None for draws or forfeits.
        """
        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT INTO game_history (player1_id, player2_id, game_type, winner_id)
                VALUES (?, ?, ?, ?)
            """, (player1_id, player2_id, game_type, winner_id))
            conn.commit()
            return True
        except Exception as e:
            print(f"❌ Error recording game match: {e}")
            return False
        finally:
            conn.close()
    
    def get_user_game_history(self, user_id, limit=10):
        """
        Get recent games played by a user with opponent information.
        """
        conn = self.get_connection()
        try:
            rows = conn.execute("""
                SELECT 
                    gh.*,
                    CASE 
                        WHEN gh.player1_id = ? THEN u2.username
                        ELSE u1.username
                    END as opponent_username,
                    CASE 
                        WHEN gh.player1_id = ? THEN gh.player2_id
                        ELSE gh.player1_id
                    END as opponent_id,
                    CASE 
                        WHEN gh.winner_id = ? THEN 'win'
                        WHEN gh.winner_id IS NULL THEN 'draw'
                        ELSE 'loss'
                    END as result
                FROM game_history gh
                JOIN users u1 ON gh.player1_id = u1.id
                JOIN users u2 ON gh.player2_id = u2.id
                WHERE gh.player1_id = ? OR gh.player2_id = ?
                ORDER BY gh.played_at DESC
                LIMIT ?
            """, (user_id, user_id, user_id, user_id, user_id, limit)).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"❌ Error getting game history: {e}")
            return []
        finally:
            conn.close()



    # ZN 
    # REGION / COMMUNITY CHAT
    # ==========================
    def save_region_message(self, sender_id, region_name, message_text):
        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT INTO messages (sender_id, receiver_id, region_name, message_text)
                VALUES (?, NULL, ?, ?)
            """, (sender_id, region_name, message_text))
            conn.commit()
        finally:
            conn.close()

    def get_region_chat(self, region_name, limit=200):
        conn = self.get_connection()
        try:
            rows = conn.execute("""
                SELECT m.message_text, m.timestamp,
                       u.username AS sender_username,
                       COALESCE(p.name, u.username) AS sender_display_name,
                       COALESCE(p.profile_pic, 'profile_pic.png') AS sender_profile_pic
                FROM messages m
                JOIN users u ON u.id = m.sender_id
                LEFT JOIN profiles p ON p.user_id = u.id
                WHERE m.region_name = ?
                  AND m.receiver_id IS NULL
                ORDER BY m.timestamp ASC
                LIMIT ?
            """, (region_name, limit)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def save_message(self, sender_id, receiver_id, message_text=None, region_name=None,
                 timestamp=None, message_type="text", media_path=None, audio_path=None, file_name=None):
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO messages (
                    sender_id, receiver_id, region_name,
                    message_type, message_text, media_path, audio_path, file_name,
                    timestamp, delivered_at, read_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), NULL, NULL)
            """, (
                sender_id, receiver_id, region_name,
                message_type, message_text, media_path, audio_path, file_name,
                timestamp
            ))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_chat_history(self, user1_id, user2_id):
        conn = self.get_connection()
        try:
            rows = conn.execute("""
                SELECT
                    id, sender_id, receiver_id, region_name,
                    message_type, message_text, media_path, audio_path, file_name,
                    timestamp, delivered_at, read_at
                FROM messages
                WHERE
                    ((sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?))
                    AND region_name IS NULL
                ORDER BY id ASC
            """, (user1_id, user2_id, user2_id, user1_id)).fetchall()

            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_region_messages(self, region_name):
        conn = self.get_connection()
        try:
            rows = conn.execute("""
                SELECT *
                FROM messages
                WHERE region_name = ?
                ORDER BY timestamp ASC
            """, (region_name,)).fetchall()

            return [dict(r) for r in rows]
        finally:
            conn.close()

    import sqlite3

    def get_connection(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def mark_delivered(self, msg_id, ts=None):
        conn = self.get_connection()
        try:
            conn.execute("""
                UPDATE messages
                SET delivered_at = COALESCE(delivered_at, COALESCE(?, CURRENT_TIMESTAMP))
                WHERE id = ?
            """, (ts, msg_id))
            conn.commit()
        finally:
            conn.close()

    def get_unread_ids(self, sender_id, receiver_id):
        conn = self.get_connection()
        try:
            rows = conn.execute("""
                SELECT id FROM messages
                WHERE sender_id=? AND receiver_id=? AND read_at IS NULL
            """, (sender_id, receiver_id)).fetchall()
            return [r["id"] for r in rows]
        finally:
            conn.close()

    def mark_read_for_chat(self, sender_id, receiver_id, ts=None):
        conn = self.get_connection()
        try:
            conn.execute("""
                UPDATE messages
                SET read_at = COALESCE(read_at, COALESCE(?, CURRENT_TIMESTAMP)),
                    delivered_at = COALESCE(delivered_at, COALESCE(?, CURRENT_TIMESTAMP))
                WHERE sender_id=? AND receiver_id=? AND read_at IS NULL
            """, (ts, ts, sender_id, receiver_id))
            conn.commit()
        finally:
            conn.close()


    def get_region_messages(self, region_name):
        conn = self.get_connection()
        try:
            rows = conn.execute("""
                SELECT * FROM messages
                WHERE region_name = ?
                ORDER BY timestamp ASC
            """, (region_name,)).fetchall()

            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_dm_streak_state(self, room):
        conn = self.get_connection()
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


    def set_dm_streak_state(self, room, streak, last_day):
        conn = self.get_connection()
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

    def mark_read(self, sender_id, receiver_id):
        conn = self.get_connection()
        conn.execute("""
            UPDATE messages
            SET read_at = datetime('now')
            WHERE sender_id = ?
            AND receiver_id = ?
            AND read_at IS NULL
        """, (sender_id, receiver_id))
        conn.commit()
        conn.close()

    
            

db_helper = DatabaseHelper()