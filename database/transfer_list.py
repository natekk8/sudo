from datetime import datetime
from database.core import get_connection, _lock


def add_to_transfer_list(player_name: str, club_tag: str, price: int,
                         discord_id: int = None, listed_by: int = None,
                         note: str = None) -> bool:
    """Wystawia zawodnika na listę transferową (lub aktualizuje cenę / notatkę).

    Zwraca True, jeśli wpis już istniał (aktualizacja), False przy nowym wpisie.
    """
    club_tag = club_tag.strip().upper()
    listed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT player_name FROM transfer_list WHERE player_name = ? COLLATE NOCASE",
                (player_name,))
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "DELETE FROM transfer_list WHERE player_name = ? COLLATE NOCASE", (player_name,))
            cursor.execute("""
                INSERT INTO transfer_list
                    (player_name, discord_id, club_tag, price, note, listed_by, listed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (player_name, discord_id, club_tag, max(0, int(price)),
                  (note or "").strip() or None, listed_by, listed_at))
            conn.commit()
            return existing is not None


def remove_from_transfer_list(player_name: str) -> bool:
    if not player_name:
        return False
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM transfer_list WHERE player_name = ? COLLATE NOCASE", (player_name,))
            conn.commit()
            return cursor.rowcount > 0


def get_transfer_list_entry(player_name: str):
    if not player_name:
        return None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM transfer_list WHERE player_name = ? COLLATE NOCASE", (player_name,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_transfer_list(limit: int = None) -> list:
    """Aktualna lista transferowa (najtańsi pierwsi).

    Wpisy osieroconych zawodników (zmiana klubu, rozwiązanie umowy, likwidacja klubu)
    są pomijane dzięki JOIN-owi z tabelą players, więc lista jest zawsze spójna.
    """
    query = """
        SELECT t.*, p.discord_id AS p_discord_id, p.expires_at AS expires_at,
               p.clause AS clause, c.name AS club_name
        FROM transfer_list t
        JOIN players p ON p.name = t.player_name COLLATE NOCASE
                      AND UPPER(p.club_tag) = UPPER(t.club_tag)
        LEFT JOIN clubs c ON UPPER(c.tag) = UPPER(t.club_tag)
        ORDER BY t.price ASC, t.listed_at DESC
    """
    params = ()
    if limit:
        query += " LIMIT ?"
        params = (int(limit),)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        result = []
        for r in cursor.fetchall():
            d = dict(r)
            d["discord_id"] = d.get("discord_id") or d.pop("p_discord_id", None)
            d.pop("p_discord_id", None)
            result.append(d)
        return result


def count_transfer_list(club_tag: str = None, valid_only: bool = True) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        if valid_only:
            query = """
                SELECT COUNT(*) FROM transfer_list t
                JOIN players p ON p.name = t.player_name COLLATE NOCASE
                              AND UPPER(p.club_tag) = UPPER(t.club_tag)
            """
            params = ()
            if club_tag:
                query += " WHERE UPPER(t.club_tag) = UPPER(?)"
                params = (club_tag.strip(),)
            cursor.execute(query, params)
        else:
            if club_tag:
                cursor.execute(
                    "SELECT COUNT(*) FROM transfer_list WHERE UPPER(club_tag) = UPPER(?)",
                    (club_tag.strip(),)
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM transfer_list")
        return cursor.fetchone()[0]


def cleanup_transfer_list() -> int:
    """Usuwa osierocone wpisy listy transferowej. Zwraca liczbę usuniętych rekordów."""
    with _lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM transfer_list WHERE NOT EXISTS (
                    SELECT 1 FROM players p
                    WHERE p.name = transfer_list.player_name COLLATE NOCASE
                      AND UPPER(p.club_tag) = UPPER(transfer_list.club_tag)
                )
            """)
            conn.commit()
            return cursor.rowcount
