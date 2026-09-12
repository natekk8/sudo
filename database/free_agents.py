from datetime import datetime
from database.core import get_connection, _lock

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
            return expired
