"""
utils/league_config.py
======================
Dynamiczne ustawienia ligi.
Zawsze sprawdza baze SQLite (tabela settings) przed env-zmiennymi.
Dzieki temu /setup moze zmieniac ustawienia w locie bez restartu bota.

Klucze settings w bazie:
  cfg_max_players        -> int  (domyslnie: MAX_PLAYERS_PER_CLUB z env)
  cfg_channel_forum      -> int  (domyslnie: CHANNEL_FORUM_ID z env)
  cfg_channel_komunikaty -> int  (domyslnie: CHANNEL_KOMUNIKATY_ID z env)
  cfg_role_federacja     -> int  (domyslnie: ROLE_FEDERACJA_ID z env)
  cfg_rola_wzorzec       -> int  (domyslnie: ROLA_WZORZEC_ID z env)
  cfg_season_label       -> str  (domyslnie: "2026/27")
  cfg_league_name        -> str  (domyslnie: "Liga Federacji")
"""

import os
import database

_DEFAULTS = {
    "cfg_max_players":        os.getenv("MAX_PLAYERS_PER_CLUB", "3"),
    "cfg_channel_forum":      os.getenv("CHANNEL_FORUM_ID", "0"),
    "cfg_channel_komunikaty": os.getenv("CHANNEL_KOMUNIKATY_ID", "0"),
    "cfg_role_federacja":     os.getenv("ROLE_FEDERACJA_ID", "0"),
    "cfg_rola_wzorzec":       os.getenv("ROLA_WZORZEC_ID", "0"),
    "cfg_season_label":       "2026/27",
    "cfg_league_name":        "Federacja Siatkówki Stołowej (FSS)",
}

_LABELS = {
    "cfg_max_players":        "Max graczy w klubie",
    "cfg_channel_forum":      "Kanal forum (ID)",
    "cfg_channel_komunikaty": "Kanal komunikatow (ID)",
    "cfg_role_federacja":     "Rola Federacji (ID)",
    "cfg_rola_wzorzec":       "Wzorzec roli gracza (ID)",
    "cfg_season_label":       "Oznaczenie sezonu",
    "cfg_league_name":        "Nazwa Federacji",
}


VALID_KEYS = set(_DEFAULTS.keys())


def get_raw(key: str) -> str:
    try:
        val = database.get_setting(key)
        if val is not None:
            return val
    except Exception:
        pass
    return _DEFAULTS.get(key, "")


def get_int(key: str) -> int:
    try:
        return int(get_raw(key))
    except (ValueError, TypeError):
        return 0


def get_str(key: str) -> str:
    return get_raw(key)


def max_players() -> int:
    return max(1, get_int("cfg_max_players"))

def channel_forum_id() -> int:
    return get_int("cfg_channel_forum")

def channel_komunikaty_id() -> int:
    return get_int("cfg_channel_komunikaty")

def role_federacja_id() -> int:
    return get_int("cfg_role_federacja")

def rola_wzorzec_id() -> int:
    return get_int("cfg_rola_wzorzec")

def season_label() -> str:
    return get_str("cfg_season_label") or "2026/27"

def league_name() -> str:
    return get_str("cfg_league_name") or "Federacja Siatkówki Stołowej (FSS)"



def set_config(key: str, value: str) -> bool:
    if key not in VALID_KEYS:
        return False
    database.set_setting(key, value.strip())
    return True


def get_all_config() -> dict:
    result = {}
    for key, label in _LABELS.items():
        result[key] = {
            "label": label,
            "value": get_raw(key),
            "default": _DEFAULTS.get(key, ""),
        }
    return result
