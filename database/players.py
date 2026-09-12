from database.core import get_connection, _lock

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

            if discord_id:
                cursor.execute("SELECT name FROM players WHERE discord_id = ?", (discord_id,))
                existing_dc = cursor.fetchone()
                if existing_dc and existing_dc["name"].lower() != name.lower():
                    cursor.execute("DELETE FROM players WHERE name = ?", (existing_dc["name"],))

            cursor.execute("SELECT expires_at, clause FROM players WHERE name = ? COLLATE NOCASE", (name,))
            old = cursor.fetchone()
            warned_7d = warned_3d = warned_1d = 0
            if old and old["expires_at"] == expires_at:
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
    if player_discord_id:
        p = get_player_by_discord_id(player_discord_id)
        if p: return p
    if player_name:
        import re
        extracted = re.findall(r'<@!?(\d+)>', str(player_name))
        if extracted:
            p = get_player_by_discord_id(int(extracted[0]))
            if p: return p
        cleaned = re.sub(r'<@!?\d+>', '', str(player_name)).strip("()[]\"' ")
        if cleaned:
            p = get_player(cleaned)
            if p: return p
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
