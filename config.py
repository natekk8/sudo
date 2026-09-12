import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Discord Token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Role IDs (z domyślnymi wartościami fallback)
ROLE_FEDERACJA_ID = int(os.getenv("ROLE_FEDERACJA_ID", "1545869517459161092"))
ROLA_WZORZEC_ID = int(os.getenv("ROLA_WZORZEC_ID", "1545869511318708244"))

# Kanały (z domyślnymi wartościami fallback)
CHANNEL_FORUM_ID = int(os.getenv("CHANNEL_FORUM_ID", "1548260165134852157"))
CHANNEL_KOMUNIKATY_ID = int(os.getenv("CHANNEL_KOMUNIKATY_ID", "1548260354264539196"))

# Zasady ligi
MAX_PLAYERS_PER_CLUB = int(os.getenv("MAX_PLAYERS_PER_CLUB", "3"))

# Ścieżki bazy danych
DB_PATH = os.getenv("DB_PATH", "liga.db")
LEGACY_JSON_DB = "baza_ligi.json"
