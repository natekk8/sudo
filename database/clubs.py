import json
from database.core import get_connection, _lock

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
    return update_club_full(old_tag, new_tag=new_tag, new_name=new_name)
