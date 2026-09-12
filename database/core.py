import sqlite3
import os
import threading
from contextlib import contextmanager
import config
from config import LEGACY_JSON_DB

_lock = threading.Lock()

@contextmanager
def get_connection():
    conn = sqlite3.connect(config.DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        conn.close()

def _migrate_columns(cursor):
    def _cols(table):
        return {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}

    players_cols = _cols("players")
    for col, typ in {
        "parent_clause": "TEXT",
        "parent_contract_expires_at": "TEXT",
        "warned_7d": "INTEGER DEFAULT 0",
        "warned_3d": "INTEGER DEFAULT 0",
        "warned_1d": "INTEGER DEFAULT 0",
    }.items():
        if col not in players_cols:
            cursor.execute(f"ALTER TABLE players ADD COLUMN {col} {typ}")

    app_cols = _cols("applications")
    for col, typ in {
        "rejected_by": "TEXT",
        "is_buyout": "INTEGER DEFAULT 0",
        "reason": "TEXT",
        "old_club_tag": "TEXT",
        "new_founder_txt": "TEXT",
        "new_board_txt": "TEXT",
    }.items():
        if col not in app_cols:
            cursor.execute(f"ALTER TABLE applications ADD COLUMN {col} {typ}")

    fa_cols = _cols("free_agents")
    for col, typ in {
        "position": "TEXT DEFAULT 'UNI'",
        "platform": "TEXT DEFAULT 'ALL'",
    }.items():
        if col not in fa_cols:
            cursor.execute(f"ALTER TABLE free_agents ADD COLUMN {col} {typ}")

def init_db():
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clubs (
                    tag TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role_board_id INTEGER NOT NULL,
                    role_player_id INTEGER NOT NULL,
                    reprezentant_dc INTEGER,
                    founder_txt TEXT,
                    board_txt TEXT,
                    board_ids TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    name TEXT PRIMARY KEY,
                    discord_id INTEGER,
                    club_tag TEXT NOT NULL,
                    parent_club_tag TEXT,
                    clause TEXT,
                    parent_clause TEXT,
                    contract_type TEXT,
                    expires_at TEXT,
                    parent_contract_expires_at TEXT,
                    warned_7d INTEGER DEFAULT 0,
                    warned_3d INTEGER DEFAULT 0,
                    warned_1d INTEGER DEFAULT 0
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS counters (
                    name TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    thread_id INTEGER,
                    message_id INTEGER,
                    applicant_id INTEGER,
                    club_name TEXT,
                    club_tag TEXT,
                    old_club_tag TEXT,
                    founder_txt TEXT,
                    board_txt TEXT,
                    new_founder_txt TEXT,
                    new_board_txt TEXT,
                    player_name TEXT,
                    player_discord_id INTEGER,
                    target_club TEXT,
                    source_club TEXT,
                    amount TEXT,
                    clause TEXT,
                    expires_at TEXT,
                    is_buyout INTEGER DEFAULT 0,
                    reason TEXT,
                    needs_player_agree INTEGER DEFAULT 0,
                    needs_target_club_agree INTEGER DEFAULT 0,
                    needs_source_club_agree INTEGER DEFAULT 0,
                    player_agreed INTEGER DEFAULT 0,
                    target_club_agreed INTEGER DEFAULT 0,
                    source_club_agreed INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'PENDING',
                    rejected_by TEXT,
                    created_at TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transfer_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_name TEXT NOT NULL,
                    player_discord_id INTEGER,
                    from_club TEXT,
                    to_club TEXT,
                    transfer_type TEXT NOT NULL,
                    amount TEXT,
                    date TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS free_agents (
                    discord_id INTEGER PRIMARY KEY,
                    player_name TEXT NOT NULL,
                    position TEXT DEFAULT 'UNI',
                    platform TEXT DEFAULT 'ALL',
                    registered_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            _migrate_columns(cursor)

            cursor.execute("SELECT value FROM settings WHERE key = 'season_initialized'")
            row = cursor.fetchone()
            if not row or row[0] != "2026_27":
                print("[Database] Inicjalizacja sezonu 2026/27: czyszczenie starych danych i zerowanie ticketów...")
                cursor.execute("DELETE FROM players")
                cursor.execute("DELETE FROM clubs")
                cursor.execute("DELETE FROM applications")
                cursor.execute("DELETE FROM transfer_history")
                cursor.execute("DELETE FROM free_agents")
                cursor.execute("INSERT OR REPLACE INTO counters (name, value) VALUES ('ticket_counter', 0)")
                cursor.execute("DELETE FROM settings WHERE key NOT LIKE 'cfg_%'")
                cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('market_status', 'OPEN')")
                cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('season_initialized', '2026_27')")
                try:
                    cursor.execute("DELETE FROM sqlite_sequence")
                except Exception:
                    pass
                conn.commit()
                try:
                    cursor.execute("VACUUM")
                except Exception:
                    pass
                print("[Database] Baza danych SQLite została wyczyszczona na sezon 2026/27 (kolejny ticket: #001).")

            conn.commit()

    if os.path.exists(LEGACY_JSON_DB):
        try:
            os.remove(LEGACY_JSON_DB)
        except Exception:
            pass

def reset_database_for_new_season():
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM players")
            cursor.execute("DELETE FROM applications")
            cursor.execute("DELETE FROM transfer_history")
            cursor.execute("DELETE FROM free_agents")
            cursor.execute("DELETE FROM clubs")
            cursor.execute("INSERT OR REPLACE INTO counters (name, value) VALUES ('ticket_counter', 0)")
            cursor.execute("DELETE FROM settings WHERE key NOT LIKE 'cfg_%'")
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('market_status', 'OPEN')")
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('season_initialized', '2026_27')")
            try:
                cursor.execute("DELETE FROM sqlite_sequence")
            except Exception:
                pass
            conn.commit()
            try:
                cursor.execute("VACUUM")
            except Exception:
                pass

    if os.path.exists(LEGACY_JSON_DB):
        try:
            os.remove(LEGACY_JSON_DB)
        except Exception:
            pass

def backup_database_vacuum(target_path: str):
    with get_connection() as conn:
        conn.execute(f"VACUUM INTO ?", (target_path,))

def get_league_stats() -> dict:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM clubs")
        club_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM players")
        player_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM free_agents")
        fa_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM applications WHERE status = 'PENDING'")
        pending_count = cursor.fetchone()[0]
        return {
            "clubs": club_count,
            "players": player_count,
            "free_agents": fa_count,
            "pending_applications": pending_count
        }

def get_db_file_stats() -> dict:
    stats = {}
    try:
        size = os.path.getsize(config.DB_PATH)
        stats["file_size_kb"] = round(size / 1024, 1)
    except FileNotFoundError:
        stats["file_size_kb"] = 0

    with get_connection() as conn:
        cursor = conn.cursor()
        for table in ["clubs", "players", "applications", "transfer_history", "free_agents", "counters"]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
            except Exception:
                stats[table] = "?"

        cursor.execute("PRAGMA journal_mode")
        stats["journal_mode"] = cursor.fetchone()[0]
        cursor.execute("PRAGMA foreign_keys")
        stats["foreign_keys"] = "ON" if cursor.fetchone()[0] else "OFF"

    return stats
