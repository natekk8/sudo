from database.core import get_connection, _lock

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
    return get_setting("market_status", "OPEN").upper() != "CLOSED"

def set_market_status(status: str, scheduled_open: str = None, scheduled_close: str = None):
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
    return {
        "status": get_setting("market_status", "OPEN"),
        "open_at": get_setting("market_open_at", None),
        "close_at": get_setting("market_close_at", None)
    }
