import sqlite3
import json
import os
import threading
from datetime import datetime
from config import DB_PATH, LEGACY_JSON_DB

from contextlib import contextmanager

_lock = threading.Lock()

@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Tabela klubów
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

            # Tabela zawodników
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    name TEXT PRIMARY KEY,
                    discord_id INTEGER,
                    club_tag TEXT NOT NULL,
                    parent_club_tag TEXT,
                    clause TEXT,
                    contract_type TEXT,
                    expires_at TEXT
                )
            """)

            # Tabela liczników (np. ticket_counter)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS counters (
                    name TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                )
            """)

            # Tabela wniosków (trwałość przycisków i procesów po restarcie)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    thread_id INTEGER,
                    message_id INTEGER,
                    applicant_id INTEGER,
                    club_name TEXT,
                    club_tag TEXT,
                    founder_txt TEXT,
                    board_txt TEXT,
                    player_name TEXT,
                    player_discord_id INTEGER,
                    target_club TEXT,
                    source_club TEXT,
                    amount TEXT,
                    clause TEXT,
                    expires_at TEXT,
                    needs_player_agree INTEGER DEFAULT 0,
                    needs_target_club_agree INTEGER DEFAULT 0,
                    needs_source_club_agree INTEGER DEFAULT 0,
                    player_agreed INTEGER DEFAULT 0,
                    target_club_agreed INTEGER DEFAULT 0,
                    source_club_agreed INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'PENDING',
                    created_at TEXT
                )
            """)
            conn.commit()

        _import_legacy_json_if_needed()

def _import_legacy_json_if_needed():
    if not os.path.exists(LEGACY_JSON_DB):
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM clubs")
        club_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM players")
        player_count = cursor.fetchone()[0]

        # Jeśli baza jest już zainicjalizowana, nie nadpisujemy
        if club_count > 0 or player_count > 0:
            return

        try:
            with open(LEGACY_JSON_DB, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[DB] Błąd odczytu {LEGACY_JSON_DB}: {e}")
            return

        print(f"[DB] Migracja danych z {LEGACY_JSON_DB} do SQLite...")
        # Licznik ticketów
        ticket_counter = data.get("ticket_counter", 0)
        cursor.execute("INSERT OR REPLACE INTO counters (name, value) VALUES ('ticket_counter', ?)", (ticket_counter,))

        # Kluby
        for tag, cdata in data.get("kluby", {}).items():
            rep_id = cdata.get("reprezentant_dc")
            board_ids_json = json.dumps([rep_id] if rep_id else [])
            cursor.execute("""
                INSERT OR REPLACE INTO clubs (tag, name, role_board_id, role_player_id, reprezentant_dc, founder_txt, board_txt, board_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tag.upper(),
                cdata.get("nazwa", tag),
                cdata.get("rola_zarzad", 0),
                cdata.get("rola_zawodnik", 0),
                rep_id,
                "",
                "",
                board_ids_json
            ))

        # Zawodnicy
        for name, pdata in data.get("zawodnicy", {}).items():
            cursor.execute("""
                INSERT OR REPLACE INTO players (name, discord_id, club_tag, parent_club_tag, clause, contract_type, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                name,
                pdata.get("gracz_dc_id"),
                pdata.get("klub"),
                pdata.get("klub_macierzysty", pdata.get("klub")),
                pdata.get("klauzula", "Brak"),
                pdata.get("typ", "TRANSFER"),
                pdata.get("wazny_do")
            ))

        conn.commit()
        print("[DB] Migracja zakończona pomyślnie!")

def get_next_ticket_id() -> str:
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM counters WHERE name = 'ticket_counter'")
            row = cursor.fetchone()
            if row:
                count = row[0] + 1
                cursor.execute("UPDATE counters SET value = ? WHERE name = 'ticket_counter'", (count,))
            else:
                count = 1
                cursor.execute("INSERT INTO counters (name, value) VALUES ('ticket_counter', 1)")
            conn.commit()
            return f"{count:03d}"

# ==================== KLUBY ====================
def add_club(tag: str, name: str, role_board_id: int, role_player_id: int, reprezentant_dc: int = None, founder_txt: str = "", board_txt: str = "", board_ids: list = None):
    board_ids = board_ids or []
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO clubs (tag, name, role_board_id, role_player_id, reprezentant_dc, founder_txt, board_txt, board_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tag.strip().upper(),
                name.strip(),
                role_board_id,
                role_player_id,
                reprezentant_dc,
                founder_txt,
                board_txt,
                json.dumps(board_ids)
            ))
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
        cursor.execute("SELECT * FROM clubs")
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["board_ids"] = json.loads(d.get("board_ids") or "[]")
            except Exception:
                d["board_ids"] = []
            result.append(d)
        return result

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

def add_or_update_player(name: str, discord_id: int, club_tag: str, parent_club_tag: str, clause: str, contract_type: str, expires_at: str):
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO players (name, discord_id, club_tag, parent_club_tag, clause, contract_type, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                name,
                discord_id,
                club_tag.strip().upper() if club_tag else None,
                parent_club_tag.strip().upper() if parent_club_tag else None,
                clause,
                contract_type,
                expires_at
            ))
            conn.commit()

def get_player(name: str):
    if not name: return None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players WHERE name = ?", (name,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_player_by_discord_id(discord_id: int):
    if not discord_id: return None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players WHERE discord_id = ?", (discord_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def delete_player(name: str):
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM players WHERE name = ?", (name,))
            conn.commit()

def get_all_players() -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players")
        return [dict(r) for r in cursor.fetchall()]

# ==================== WNIOSKI (APPLICATIONS) ====================
def create_application(
    app_type: str,
    applicant_id: int,
    club_name: str = None,
    club_tag: str = None,
    founder_txt: str = None,
    board_txt: str = None,
    player_name: str = None,
    player_discord_id: int = None,
    target_club: str = None,
    source_club: str = None,
    amount: str = None,
    clause: str = None,
    expires_at: str = None,
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
                    type, applicant_id, club_name, club_tag, founder_txt, board_txt,
                    player_name, player_discord_id, target_club, source_club, amount,
                    clause, expires_at, needs_player_agree, needs_target_club_agree,
                    needs_source_club_agree, player_agreed, target_club_agreed,
                    source_club_agreed, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 'PENDING', ?)
            """, (
                app_type, applicant_id, club_name, club_tag, founder_txt, board_txt,
                player_name, player_discord_id, target_club, source_club, amount,
                clause, expires_at,
                1 if needs_player_agree else 0,
                1 if needs_target_club_agree else 0,
                1 if needs_source_club_agree else 0,
                created_at
            ))
            app_id = cursor.lastrowid
            conn.commit()
            return app_id

def set_application_message(app_id: int, thread_id: int, message_id: int):
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE applications SET thread_id = ?, message_id = ? WHERE id = ?", (thread_id, message_id, app_id))
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
        cursor.execute("SELECT * FROM applications WHERE status = 'PENDING' AND message_id IS NOT NULL")
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
            cursor.execute(f"UPDATE applications SET {col} = ? WHERE id = ?", (1 if value else 0, app_id))
            conn.commit()

def set_application_status(app_id: int, status: str):
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE applications SET status = ? WHERE id = ?", (status, app_id))
            conn.commit()
