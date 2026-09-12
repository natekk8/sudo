from datetime import datetime
from database.core import get_connection, _lock

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
