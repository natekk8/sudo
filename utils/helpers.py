import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import discord
from config import ROLE_FEDERACJA_ID
import database

# ─── Strefa czasowa Polska ───
try:
    from zoneinfo import ZoneInfo
    WARSAW_TZ = ZoneInfo("Europe/Warsaw")
except Exception:
    # Fallback na Windows bez pakietu tzdata
    from datetime import timezone, timedelta
    WARSAW_TZ = timezone(timedelta(hours=1))

def get_now_warsaw() -> datetime:
    """Zwraca obecny czas w strefie Europe/Warsaw (naive datetime do porównań ze stringami w SQLite)."""
    try:
        return datetime.now(WARSAW_TZ).replace(tzinfo=None)
    except Exception:
        return datetime.now()

# ─── Walidacje ───
def clean_tag(tag: str) -> str:
    if not tag: return ""
    return tag.strip().upper()

def is_valid_tag(tag: str) -> bool:
    """Dokładnie 3 litery lub cyfry (np. LAZ, FC1)."""
    return bool(re.match(r'^[A-Z0-9]{3}$', tag.strip().upper() if tag else ""))

def extract_ids(text: str) -> list:
    if not text: return []
    return [int(uid) for uid in re.findall(r'<@!?(\d+)>', text)]

def safe_thread_name(name: str) -> str:
    """Obcina nazwę wątku do limitu Discord API (100 znaków)."""
    return name[:100]

# ─── Uprawnienia ───
def is_federation(member: discord.Member) -> bool:
    if not member or not hasattr(member, "roles"): return False
    return any(r.id == ROLE_FEDERACJA_ID for r in member.roles)

def is_club_board_or_owner(member: discord.Member, club_tag: str) -> bool:
    if not member or not club_tag: return False
    club = database.get_club(club_tag)
    if not club: return False

    role_board_id = club.get("role_board_id")
    if role_board_id and any(r.id == role_board_id for r in getattr(member, "roles", [])):
        return True
    board_ids = club.get("board_ids") or []
    if member.id in board_ids: return True
    if member.id == club.get("reprezentant_dc"): return True
    return False

# ─── Członkowie Discorda ───
async def get_or_fetch_member(guild: discord.Guild, user_id: int):
    """Pobiera członka z cache, a w razie braku (po restarcie) odpytuje API Discord."""
    if not user_id or not guild: return None
    member = guild.get_member(user_id)
    if member: return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.HTTPException):
        return None

# ─── Blokada spamu ticketów ───
def has_open_ticket(guild: discord.Guild, user_id: int) -> bool:
    """Sprawdza czy użytkownik ma już otwarty kanał ticketu."""
    if not guild: return False
    for channel in guild.text_channels:
        overwrites = channel.overwrites
        for target, overwrite in overwrites.items():
            if isinstance(target, discord.Member) and target.id == user_id:
                if overwrite.view_channel and overwrite.send_messages:
                    # Kanał widoczny dla tego użytkownika – sprawdź czy to ticket (prefix nazwy)
                    prefixes = ("rejestracja-", "kontrakt-", "transfer-", "wypozyczenie-",
                                "aneks-", "rozwiazanie-", "rebrand-", "zarzadzanie-")
                    if any(channel.name.startswith(p) for p in prefixes):
                        return True
    return False

# ─── Daty i Terminy ───
def parse_expiry_date(user_input: str) -> str | None:
    if not user_input: return None
    user_input = user_input.strip()

    match_days = re.match(r'^(\d+)(\s*(dni|d|day|days))?$', user_input, re.IGNORECASE)
    if match_days:
        days = int(match_days.group(1))
        if days <= 0 or days > 3650: return None
        try:
            return (get_now_warsaw() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        except OverflowError:
            return None

    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(user_input, fmt)
            dt = dt.replace(hour=23, minute=59, second=59)
            if dt < get_now_warsaw(): return None
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None

def parse_schedule_datetime(user_input: str) -> str | None:
    """
    Parsuje datę i godzinę harmonogramu rynku.
    Obsługuje:
    - Format względny: '2h', '30m', '3d', '7 dni'
    - Format bezwzględny: 'DD.MM.YYYY HH:MM', 'YYYY-MM-DD HH:MM', 'DD.MM.YYYY' (godz. 23:59:59) itp.
    Zwraca string 'YYYY-MM-DD HH:MM:SS' w strefie polskiej lub None.
    """
    if not user_input: return None
    user_input = user_input.strip()

    m_rel = re.match(r'^(\d+)\s*(h|godz|godzin|godziny|m|min|minut|d|dni|day|days)$', user_input, re.IGNORECASE)
    if m_rel:
        val = int(m_rel.group(1))
        unit = m_rel.group(2).lower()
        now = get_now_warsaw()
        if unit in ('m', 'min', 'minut'):
            dt = now + timedelta(minutes=val)
        elif unit in ('h', 'godz', 'godzin', 'godziny'):
            dt = now + timedelta(hours=val)
        else:
            dt = now + timedelta(days=val)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    formats = [
        ("%d.%m.%Y %H:%M:%S", False),
        ("%d.%m.%Y %H:%M", False),
        ("%Y-%m-%d %H:%M:%S", False),
        ("%Y-%m-%d %H:%M", False),
        ("%d/%m/%Y %H:%M:%S", False),
        ("%d/%m/%Y %H:%M", False),
        ("%d.%m.%Y", True),
        ("%Y-%m-%d", True),
        ("%d/%m/%Y", True),
    ]
    for fmt, is_date_only in formats:
        try:
            dt = datetime.strptime(user_input, fmt)
            if is_date_only:
                dt = dt.replace(hour=23, minute=59, second=59)
            if dt < get_now_warsaw():
                return None
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None

# ─── Kwoty ───
def parse_amount(text: str) -> int:
    if not text: return 0
    t = re.sub(r'[\s,]', '', str(text).strip())
    return int(t) if re.match(r'^\d+$', t) else 0

def validate_amount_input(text: str) -> bool:
    if not text: return False
    t = re.sub(r'[\s,]', '', str(text).strip())
    if t.lower() == 'brak': return True
    return bool(re.match(r'^\d+$', t))

# ─── Formatowanie ───
def format_expiry_discord(expires_at: str) -> str:
    if not expires_at: return "Brak"
    try:
        dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
        # Zakładamy, że data jest w strefie Europe/Warsaw
        dt = dt.replace(tzinfo=WARSAW_TZ)
        ts = int(dt.timestamp())
        return f"<t:{ts}:R> (<t:{ts}:D>)"
    except Exception:
        return expires_at

def build_squad_bar(count: int, max_count: int) -> str:
    filled = "■" * count
    empty = "□" * (max_count - count)
    label = "Kadra pełna ⛔" if count >= max_count else f"{max_count - count} wolne miejsce{'a' if max_count - count > 1 else ''}"
    return f"`[{filled}{empty}] {count}/{max_count}` · {label}"

# ─── Discord Helpers ───
async def ping_representatives(thread: discord.Thread, target_tag: str, source_tag: str = None):
    ids = []
    for tag in filter(None, [target_tag, source_tag]):
        c = database.get_club(tag)
        if c:
            if c.get("reprezentant_dc"): ids.append(c["reprezentant_dc"])
            ids.extend(c.get("board_ids", []))
    ids = [uid for uid in set(ids) if uid]
    if ids and thread:
        mentions = " ".join([f"<@{uid}>" for uid in ids])
        await thread.send(
            f"🔔 **Wymagana uwaga:** {mentions}\n"
            f"> Użyjcie przycisków powyżej, aby wydać oświadczenie.",
            allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False)
        )

async def send_dm(client: discord.Client, user_id: int, content: str):
    if not user_id: return
    try:
        user = await client.fetch_user(user_id)
        if user: await user.send(content)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass
