import sqlite3
import os
import shutil
import threading
from contextlib import contextmanager
import config
from config import LEGACY_JSON_DB

_lock = threading.Lock()
PERSISTENT_BACKUP_PATH = getattr(config, "PERSISTENT_BACKUP_PATH", "liga_persistent.db")

def _is_test_env() -> bool:
    db_name = os.path.basename(getattr(config, "DB_PATH", "")).lower()
    return "test" in db_name or "temp" in db_name

def sync_persistent_backup():
    """Tworzy bezpieczną kopię bazy produkcyjnej do PERSISTENT_BACKUP_PATH."""
    if _is_test_env():
        return
    try:
        db_path = getattr(config, "DB_PATH", "liga.db")
        if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
            shutil.copy2(db_path, PERSISTENT_BACKUP_PATH)
    except Exception as e:
        print(f"[DB] Błąd tworzenia trwałego backupu: {e}")

def _try_restore_from_persistent():
    """Przywraca bazę z PERSISTENT_BACKUP_PATH jeśli DB_PATH nie istnieje lub jest pusta, a persistent ma dane."""
    if _is_test_env():
        return
    try:
        db_path = getattr(config, "DB_PATH", "liga.db")
        if not os.path.exists(PERSISTENT_BACKUP_PATH):
            return

        # Sprawdź czy persistent ma tabele i dane
        p_conn = sqlite3.connect(PERSISTENT_BACKUP_PATH)
        p_cur = p_conn.cursor()
        p_clubs = 0
        p_players = 0
        try:
            p_clubs = p_cur.execute("SELECT COUNT(*) FROM clubs").fetchone()[0]
            p_players = p_cur.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        except Exception:
            pass
        p_conn.close()

        if p_clubs == 0 and p_players == 0:
            return

        # Sprawdź czy obecna baza DB_PATH ma dane
        current_has_data = False
        if os.path.exists(db_path):
            try:
                c_conn = sqlite3.connect(db_path)
                c_cur = c_conn.cursor()
                c_clubs = c_cur.execute("SELECT COUNT(*) FROM clubs").fetchone()[0]
                c_players = c_cur.execute("SELECT COUNT(*) FROM players").fetchone()[0]
                c_conn.close()
                if c_clubs > 0 or c_players > 0:
                    current_has_data = True
            except Exception:
                pass

        if not current_has_data:
            print(f"[DB] WYKRYTO PUSTĄ BAZĘ {db_path}! Przywracanie z trwałego backupu {PERSISTENT_BACKUP_PATH} ({p_clubs} klubów, {p_players} graczy)...")
            shutil.copy2(PERSISTENT_BACKUP_PATH, db_path)
            print("[DB] ✅ Pomyślnie przywrócono bazę z trwałego backupu!")
    except Exception as e:
        print(f"[DB] Błąd auto-przywracania z trwałego backupu: {e}")

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
    _try_restore_from_persistent()
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

            # Bezpieczna inicjalizacja domyślnych ustawień (bez usuwania jakichkolwiek danych użytkownika)
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('market_status', 'OPEN')")
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('season_initialized', '2026_27')")
            cursor.execute("INSERT OR IGNORE INTO counters (name, value) VALUES ('ticket_counter', 0)")
            conn.commit()

    sync_persistent_backup()

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

    sync_persistent_backup()

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
