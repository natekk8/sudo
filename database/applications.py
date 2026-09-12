from datetime import datetime
from database.core import get_connection, _lock

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

def reset_stuck_processing_applications():
    """Resetuje wnioski zablokowane w statusie PROCESSING z powrotem do PENDING przy restarcie bota."""
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE applications SET status = 'PENDING' WHERE status = 'PROCESSING'")
            conn.commit()

def revert_application_status(app_id: int, old_status: str = "PENDING"):
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

def restore_application(app_data: dict) -> int:
    """Odtwarza lub aktualizuje wniosek z podanymi polami (np. odczytanymi z embeda na forum)."""
    created_at = app_data.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    app_id = app_data.get("id")
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            if app_id:
                cursor.execute("""
                    INSERT OR REPLACE INTO applications (
                        id, type, applicant_id, club_name, club_tag, old_club_tag,
                        founder_txt, board_txt, new_founder_txt, new_board_txt,
                        player_name, player_discord_id,
                        target_club, source_club, amount, clause, expires_at,
                        is_buyout, reason,
                        needs_player_agree, needs_target_club_agree, needs_source_club_agree,
                        player_agreed, target_club_agreed, source_club_agreed,
                        status, rejected_by, created_at, thread_id, message_id
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?,
                        ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                """, (
                    app_id,
                    app_data.get("type", "PODPISANIE"),
                    app_data.get("applicant_id"),
                    app_data.get("club_name"),
                    app_data.get("club_tag"),
                    app_data.get("old_club_tag"),
                    app_data.get("founder_txt"),
                    app_data.get("board_txt"),
                    app_data.get("new_founder_txt"),
                    app_data.get("new_board_txt"),
                    app_data.get("player_name"),
                    app_data.get("player_discord_id"),
                    app_data.get("target_club"),
                    app_data.get("source_club"),
                    app_data.get("amount"),
                    app_data.get("clause"),
                    app_data.get("expires_at"),
                    1 if app_data.get("is_buyout") else 0,
                    app_data.get("reason"),
                    1 if app_data.get("needs_player_agree") else 0,
                    1 if app_data.get("needs_target_club_agree") else 0,
                    1 if app_data.get("needs_source_club_agree") else 0,
                    1 if app_data.get("player_agreed") else 0,
                    1 if app_data.get("target_club_agreed") else 0,
                    1 if app_data.get("source_club_agreed") else 0,
                    app_data.get("status", "PENDING"),
                    app_data.get("rejected_by"),
                    created_at,
                    app_data.get("thread_id"),
                    app_data.get("message_id")
                ))
                conn.commit()
                return app_id
            else:
                return create_application(
                    app_type=app_data.get("type", "PODPISANIE"),
                    applicant_id=app_data.get("applicant_id"),
                    club_name=app_data.get("club_name"),
                    club_tag=app_data.get("club_tag"),
                    old_club_tag=app_data.get("old_club_tag"),
                    founder_txt=app_data.get("founder_txt"),
                    board_txt=app_data.get("board_txt"),
                    new_founder_txt=app_data.get("new_founder_txt"),
                    new_board_txt=app_data.get("new_board_txt"),
                    player_name=app_data.get("player_name"),
                    player_discord_id=app_data.get("player_discord_id"),
                    target_club=app_data.get("target_club"),
                    source_club=app_data.get("source_club"),
                    amount=app_data.get("amount"),
                    clause=app_data.get("clause"),
                    expires_at=app_data.get("expires_at"),
                    is_buyout=bool(app_data.get("is_buyout")),
                    reason=app_data.get("reason"),
                    needs_player_agree=bool(app_data.get("needs_player_agree")),
                    needs_target_club_agree=bool(app_data.get("needs_target_club_agree")),
                    needs_source_club_agree=bool(app_data.get("needs_source_club_agree"))
                )
