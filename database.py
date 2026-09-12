import sqlite3
import json
import os
import threading
from datetime import datetime
from contextlib import contextmanager
from config import DB_PATH, LEGACY_JSON_DB

_lock = threading.Lock()

@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        conn.close()

# ==================== INICJALIZACJA ====================
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
            conn.commit()

    _import_legacy_json_if_needed()

def _migrate_columns(cursor):
    """Bezpieczne dodanie brakujących kolumn do istniejących tabel."""
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

def _import_legacy_json_if_needed():
    if not os.path.exists(LEGACY_JSON_DB):
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM clubs")
        if cursor.fetchone()[0] > 0:
            return

        try:
            with open(LEGACY_JSON_DB, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[DB] Błąd odczytu {LEGACY_JSON_DB}: {e}")
            return

        if not data.get("kluby") and not data.get("zawodnicy"):
            return

        print(f"[DB] Migracja z {LEGACY_JSON_DB}...")
        cursor.execute("INSERT OR REPLACE INTO counters (name, value) VALUES ('ticket_counter', ?)",
                       (data.get("ticket_counter", 0),))

        for tag, cd in data.get("kluby", {}).items():
            rep_id = cd.get("reprezentant_dc")
            cursor.execute("""
                INSERT OR REPLACE INTO clubs (tag, name, role_board_id, role_player_id, reprezentant_dc, founder_txt, board_txt, board_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (tag.upper(), cd.get("nazwa", tag), cd.get("rola_zarzad", 0),
                  cd.get("rola_zawodnik", 0), rep_id, "", "", json.dumps([rep_id] if rep_id else [])))

        for name, pd in data.get("zawodnicy", {}).items():
            cursor.execute("""
                INSERT OR REPLACE INTO players (name, discord_id, club_tag, parent_club_tag, clause, contract_type, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, pd.get("gracz_dc_id"), pd.get("klub"),
                  pd.get("klub_macierzysty", pd.get("klub")),
                  pd.get("klauzula", "Brak"), pd.get("typ", "TRANSFER"), pd.get("wazny_do")))

        conn.commit()
        print("[DB] Migracja zakończona.")

# ==================== LICZNIKI ====================
def get_next_ticket_id() -> str:
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM counters WHERE name = 'ticket_counter'")
            row = cursor.fetchone()
            count = (row[0] + 1) if row else 1
            cursor.execute("INSERT OR REPLACE INTO counters (name, value) VALUES ('ticket_counter', ?)", (count,))
            conn.commit()
            return f"{count:03d}"

# ==================== KLUBY ====================
def add_club(tag: str, name: str, role_board_id: int, role_player_id: int,
             reprezentant_dc: int = None, founder_txt: str = "", board_txt: str = "",
             board_ids: list = None):
    board_ids = board_ids or []
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO clubs (tag, name, role_board_id, role_player_id, reprezentant_dc, founder_txt, board_txt, board_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (tag.strip().upper(), name.strip(), role_board_id, role_player_id,
                  reprezentant_dc, founder_txt, board_txt, json.dumps(board_ids)))
            conn.commit()

def get_club(tag: str):
    if not tag: return None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clubs WHERE tag = ?", (tag.strip().upper(),))
        row = cursor.fetchone()
        if not row: return None
        res = dict(row)
        try:
            res["board_ids"] = json.loads(res.get("board_ids") or "[]")
        except Exception:
            res["board_ids"] = []
        return res

def get_all_clubs() -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clubs ORDER BY name")
        result = []
        for r in cursor.fetchall():
            d = dict(r)
            try:
                d["board_ids"] = json.loads(d.get("board_ids") or "[]")
            except Exception:
                d["board_ids"] = []
            result.append(d)
        return result

def update_club_full(old_tag: str, new_tag: str = None, new_name: str = None,
                     new_founder_txt: str = None, new_board_txt: str = None,
                     new_board_ids: list = None, new_rep_id: int = None):
    """
    Kaskadowa aktualizacja klubu: tag, nazwa, właściciel, zarząd.
    Aktualizuje tabelę clubs oraz kaskadowo graczy i historię transferów.
    """
    old_tag = old_tag.strip().upper()
    new_tag = new_tag.strip().upper() if new_tag else old_tag
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM clubs WHERE tag = ?", (old_tag,))
            club = cursor.fetchone()
            if not club:
                return False

            final_name = new_name.strip() if new_name and new_name.lower() != "bez zmian" else club["name"]
            final_founder = new_founder_txt.strip() if new_founder_txt and new_founder_txt.lower() != "bez zmian" else club["founder_txt"]
            final_board_txt = new_board_txt.strip() if new_board_txt and new_board_txt.lower() != "bez zmian" else club["board_txt"]
            final_board_ids = json.dumps(new_board_ids) if new_board_ids is not None else club["board_ids"]
            final_rep = new_rep_id if new_rep_id is not None else club["reprezentant_dc"]

            cursor.execute("""
                UPDATE clubs SET
                    tag = ?, name = ?, founder_txt = ?, board_txt = ?,
                    board_ids = ?, reprezentant_dc = ?
                WHERE tag = ?
            """, (new_tag, final_name, final_founder, final_board_txt, final_board_ids, final_rep, old_tag))

            if new_tag != old_tag:
                cursor.execute("UPDATE players SET club_tag = ? WHERE club_tag = ?", (new_tag, old_tag))
                cursor.execute("UPDATE players SET parent_club_tag = ? WHERE parent_club_tag = ?", (new_tag, old_tag))
                cursor.execute("UPDATE transfer_history SET from_club = ? WHERE from_club = ?", (new_tag, old_tag))
                cursor.execute("UPDATE transfer_history SET to_club = ? WHERE to_club = ?", (new_tag, old_tag))

            conn.commit()
            return True

def rebrand_club(old_tag: str, new_tag: str, new_name: str):
    """Kaskadowy rebranding: zmienia tag i nazwę klubu oraz aktualizuje wszystkich graczy."""
    return update_club_full(old_tag, new_tag=new_tag, new_name=new_name)

# ==================== ZAWODNICY ====================
def get_club_player_count(club_tag: str) -> int:
    if not club_tag: return 0
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM players WHERE UPPER(club_tag) = ?", (club_tag.strip().upper(),))
        return cursor.fetchone()[0]

def get_club_players(club_tag: str) -> list:
    if not club_tag: return []
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players WHERE UPPER(club_tag) = ?", (club_tag.strip().upper(),))
        return [dict(r) for r in cursor.fetchall()]

def add_or_update_player(name: str, discord_id: int, club_tag: str, parent_club_tag: str,
                          clause: str, contract_type: str, expires_at: str,
                          parent_contract_expires_at: str = None, parent_clause: str = None):
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()

            # Jeśli przekazano discord_id, upewnij się że nie ma duplikatu pod inną nazwą
            if discord_id:
                cursor.execute("SELECT name FROM players WHERE discord_id = ?", (discord_id,))
                existing_dc = cursor.fetchone()
                if existing_dc and existing_dc["name"].lower() != name.lower():
                    cursor.execute("DELETE FROM players WHERE name = ?", (existing_dc["name"],))

            # Sprawdź czy zmieniamy datę (reset flag ostrzeżeń)
            cursor.execute("SELECT expires_at, clause FROM players WHERE name = ? COLLATE NOCASE", (name,))
            old = cursor.fetchone()
            warned_7d = warned_3d = warned_1d = 0
            if old and old["expires_at"] == expires_at:
                # Data się nie zmieniła – zachowaj flagi
                cursor.execute("SELECT warned_7d, warned_3d, warned_1d FROM players WHERE name = ? COLLATE NOCASE", (name,))
                flags = cursor.fetchone()
                if flags:
                    warned_7d, warned_3d, warned_1d = flags["warned_7d"], flags["warned_3d"], flags["warned_1d"]

            cursor.execute("""
                INSERT OR REPLACE INTO players
                    (name, discord_id, club_tag, parent_club_tag, clause, parent_clause,
                     contract_type, expires_at, parent_contract_expires_at,
                     warned_7d, warned_3d, warned_1d)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name, discord_id,
                club_tag.strip().upper() if club_tag else None,
                parent_club_tag.strip().upper() if parent_club_tag else None,
                clause, parent_clause, contract_type, expires_at,
                parent_contract_expires_at, warned_7d, warned_3d, warned_1d
            ))
            conn.commit()

def extend_player_contract(name: str, expires_at: str, clause: str, discord_id: int = None):
    """Aktualizacja kontraktu z resetem flag ostrzeżeń (Aneks). Obsługuje dopasowanie po name lub discord_id."""
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            if discord_id:
                cursor.execute("""
                    UPDATE players SET expires_at = ?, clause = ?,
                        warned_7d = 0, warned_3d = 0, warned_1d = 0
                    WHERE discord_id = ? OR name = ? COLLATE NOCASE
                """, (expires_at, clause, discord_id, name))
            else:
                cursor.execute("""
                    UPDATE players SET expires_at = ?, clause = ?,
                        warned_7d = 0, warned_3d = 0, warned_1d = 0
                    WHERE name = ? COLLATE NOCASE
                """, (expires_at, clause, name))
            conn.commit()

def terminate_player_contract(name: str, discord_id: int = None):
    """Usuwa gracza z bazy – rozwiązanie kontraktu."""
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            if discord_id:
                cursor.execute("DELETE FROM players WHERE discord_id = ? OR name = ? COLLATE NOCASE", (discord_id, name))
            else:
                cursor.execute("DELETE FROM players WHERE name = ? COLLATE NOCASE", (name,))
            conn.commit()

def get_player(name: str):
    if not name: return None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players WHERE name = ? COLLATE NOCASE", (name,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_player_by_discord_id(discord_id: int):
    if not discord_id: return None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players WHERE discord_id = ?", (discord_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def is_player_under_contract(player_name: str, player_discord_id: int = None):
    """Zwraca rekord gracza jeśli ma aktywny kontrakt, None w przeciwnym razie."""
    if player_discord_id:
        p = get_player_by_discord_id(player_discord_id)
        if p: return p
    if player_name:
        p = get_player(player_name)
        if p: return p
    return None

def delete_player(name: str, discord_id: int = None):
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            if discord_id:
                cursor.execute("DELETE FROM players WHERE discord_id = ? OR name = ? COLLATE NOCASE", (discord_id, name))
            else:
                cursor.execute("DELETE FROM players WHERE name = ? COLLATE NOCASE", (name,))
            conn.commit()

def get_all_players() -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players")
        return [dict(r) for r in cursor.fetchall()]

def set_player_warning_flag(name: str, flag: str):
    allowed = {"warned_7d", "warned_3d", "warned_1d"}
    if flag not in allowed: return
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE players SET {flag} = 1 WHERE name = ?", (name,))
            conn.commit()

# ==================== HISTORIA TRANSFERÓW ====================
def add_transfer_history(player_name: str, player_discord_id: int, from_club: str,
                          to_club: str, transfer_type: str, amount: str = None):
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO transfer_history (player_name, player_discord_id, from_club, to_club, transfer_type, amount, date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (player_name, player_discord_id, from_club, to_club, transfer_type, amount, date))
            conn.commit()

def get_player_transfer_history(player_name: str, player_discord_id: int = None) -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        if player_discord_id:
            cursor.execute("""
                SELECT * FROM transfer_history
                WHERE player_name = ? OR player_discord_id = ?
                ORDER BY date DESC LIMIT 10
            """, (player_name, player_discord_id))
        else:
            cursor.execute("""
                SELECT * FROM transfer_history WHERE player_name = ?
                ORDER BY date DESC LIMIT 10
            """, (player_name,))
        return [dict(r) for r in cursor.fetchall()]

# ==================== WOLNI AGENCI (GIEŁDA) ====================
def register_free_agent(discord_id: int, player_name: str):
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT OR REPLACE INTO free_agents (discord_id, player_name, registered_at)
                VALUES (?, ?, ?)
            """, (discord_id, player_name, date))
            conn.commit()

def remove_free_agent(discord_id: int):
    if not discord_id: return
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM free_agents WHERE discord_id = ?", (discord_id,))
            conn.commit()

def get_free_agents_paginated(limit: int = 25) -> tuple:
    """Zwraca (lista_agentów, total_count). Bezpieczne wobec limitu 4096 znaków."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM free_agents")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT * FROM free_agents ORDER BY registered_at DESC LIMIT ?", (limit,))
        agents = [dict(r) for r in cursor.fetchall()]
        return agents, total

def get_all_free_agents() -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM free_agents ORDER BY registered_at")
        return [dict(r) for r in cursor.fetchall()]

def is_free_agent(discord_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM free_agents WHERE discord_id = ?", (discord_id,))
        return cursor.fetchone() is not None

def cleanup_expired_free_agents(days: int = 14):
    """Usuwa z giełdy ogłoszenia starsze niż `days` dni."""
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT discord_id, player_name FROM free_agents "
                "WHERE registered_at < datetime('now', ?)",
                (f"-{days} days",)
            )
            expired = [dict(r) for r in cursor.fetchall()]
            cursor.execute(
                "DELETE FROM free_agents WHERE registered_at < datetime('now', ?)",
                (f"-{days} days",)
            )
            conn.commit()
            return expired  # Lista usuniętych, do wysyłania DM

def backup_database_vacuum(target_path: str):
    """Wykonuje VACUUM INTO – atomowy zapis spójnej kopii bazy SQLite (WAL-safe)."""
    with get_connection() as conn:
        conn.execute(f"VACUUM INTO ?", (target_path,))

# ==================== WNIOSKI (APPLICATIONS) ====================
def create_application(
    app_type: str, applicant_id: int,
    club_name: str = None, club_tag: str = None, old_club_tag: str = None,
    founder_txt: str = None, board_txt: str = None,
    new_founder_txt: str = None, new_board_txt: str = None,
    player_name: str = None, player_discord_id: int = None,
    target_club: str = None, source_club: str = None,
    amount: str = None, clause: str = None, expires_at: str = None,
    is_buyout: bool = False, reason: str = None,
    needs_player_agree: bool = False,
    needs_target_club_agree: bool = False,
    needs_source_club_agree: bool = False
) -> int:
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO applications (
                    type, applicant_id, club_name, club_tag, old_club_tag,
                    founder_txt, board_txt, new_founder_txt, new_board_txt,
                    player_name, player_discord_id,
                    target_club, source_club, amount, clause, expires_at,
                    is_buyout, reason,
                    needs_player_agree, needs_target_club_agree, needs_source_club_agree,
                    player_agreed, target_club_agreed, source_club_agreed,
                    status, rejected_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 'PENDING', NULL, ?)
            """, (
                app_type, applicant_id, club_name, club_tag, old_club_tag,
                founder_txt, board_txt, new_founder_txt, new_board_txt,
                player_name, player_discord_id,
                target_club, source_club, amount, clause, expires_at,
                1 if is_buyout else 0, reason,
                1 if needs_player_agree else 0,
                1 if needs_target_club_agree else 0,
                1 if needs_source_club_agree else 0,
                created_at
            ))
            app_id = cursor.lastrowid
            conn.commit()
            return app_id

def try_claim_application_for_approval(app_id: int):
    """
    Atomowy CAS: zmienia status PENDING → PROCESSING.
    Zwraca dict wniosku jeśli się powiodło, None jeśli wniosek był już przetwarzany.
    Chroni przed TOCTOU przy podwójnym kliknięciu przez Federację.
    """
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
            row = cursor.fetchone()
            if not row or row["status"] != "PENDING":
                return None
            cursor.execute(
                "UPDATE applications SET status = 'PROCESSING' WHERE id = ? AND status = 'PENDING'",
                (app_id,)
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
            return dict(row)

def revert_application_status(app_id: int, old_status: str = "PENDING"):
    """Rollback statusu PROCESSING → PENDING po błędzie krytycznym Discord API."""
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE applications SET status = ? WHERE id = ? AND status = 'PROCESSING'",
                (old_status, app_id)
            )
            conn.commit()

def set_application_message(app_id: int, thread_id: int, message_id: int):
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE applications SET thread_id = ?, message_id = ? WHERE id = ?",
                           (thread_id, message_id, app_id))
            conn.commit()

def get_application(app_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_pending_applications() -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM applications WHERE status IN ('PENDING', 'PROCESSING') AND message_id IS NOT NULL"
        )
        return [dict(r) for r in cursor.fetchall()]

def get_stale_pending_applications(hours: int = 48) -> list:
    """Wniosek bez decyzji po X godzinach."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM applications WHERE status = 'PENDING'
            AND created_at < datetime('now', ?)
        """, (f"-{hours} hours",))
        return [dict(r) for r in cursor.fetchall()]

def set_application_agreement(app_id: int, agree_type: str, value: bool = True):
    allowed = {
        "player": "player_agreed",
        "target_club": "target_club_agreed",
        "source_club": "source_club_agreed"
    }
    col = allowed.get(agree_type)
    if not col: return
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE applications SET {col} = ? WHERE id = ?",
                           (1 if value else 0, app_id))
            conn.commit()

def set_application_status(app_id: int, status: str, rejected_by: str = None):
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE applications SET status = ?, rejected_by = ? WHERE id = ?",
                (status, rejected_by, app_id)
            )
            conn.commit()

# ==================== STATYSTYKI ====================
def get_league_stats() -> dict:
    """Dane statystyczne ligi do komendy !liga_status."""
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
    """Rozmiar pliku bazy danych i liczba wierszy per tabela."""
    stats = {}
    try:
        size = os.path.getsize(DB_PATH)
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

# ==================== USTAWIENIA I RYNEK TRANSFEROWY ====================
def get_setting(key: str, default: str = None) -> str:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row and row[0] is not None else default

def set_setting(key: str, value: str):
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            val_str = str(value) if value is not None else None
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, val_str))
            conn.commit()

def delete_setting(key: str):
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()

def is_market_open() -> bool:
    """Zwraca True jeśli rynek jest otwarty (domyślnie OPEN)."""
    return get_setting("market_status", "OPEN").upper() != "CLOSED"

def set_market_status(status: str, scheduled_open: str = None, scheduled_close: str = None):
    """
    Ustawia stan rynku ('OPEN' lub 'CLOSED') oraz opcjonalne planowane daty.
    """
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('market_status', ?)", (status.upper(),))
            if scheduled_open is not None:
                cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('market_open_at', ?)",
                               (str(scheduled_open) if scheduled_open else None,))
            if scheduled_close is not None:
                cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('market_close_at', ?)",
                               (str(scheduled_close) if scheduled_close else None,))
            conn.commit()

def get_market_state() -> dict:
    """Zwraca słownik ze stanem rynku i zaplanowanymi datami."""
    return {
        "status": get_setting("market_status", "OPEN"),
        "open_at": get_setting("market_open_at", None),
        "close_at": get_setting("market_close_at", None)
    }

# ==================== RESET NA SEZON 2026/27 ====================
def reset_database_for_new_season():
    """Czyści wszystkie tabele ligowe, przygotowując bazę na sezon 2026/27."""
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM players")
            cursor.execute("DELETE FROM applications")
            cursor.execute("DELETE FROM transfer_history")
            cursor.execute("DELETE FROM free_agents")
            cursor.execute("DELETE FROM clubs")
            cursor.execute("INSERT OR REPLACE INTO counters (name, value) VALUES ('ticket_counter', 0)")
            cursor.execute("DELETE FROM settings")
            cursor.execute("INSERT INTO settings (key, value) VALUES ('market_status', 'OPEN')")
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
            with open(LEGACY_JSON_DB, "w", encoding="utf-8") as f:
                json.dump({"kluby": {}, "zawodnicy": {}, "ticket_counter": 0}, f, indent=4)
        except Exception:
            pass

