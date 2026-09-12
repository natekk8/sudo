import re
from datetime import datetime, timedelta
import discord
from config import ROLE_FEDERACJA_ID
import database

def clean_tag(tag: str) -> str:
    if not tag:
        return ""
    return tag.strip().upper()

def extract_ids(text: str) -> list[int]:
    if not text:
        return []
    return [int(uid) for uid in re.findall(r'<@!?(\d+)>', text)]

def is_federation(member: discord.Member) -> bool:
    if not member or not hasattr(member, "roles"):
        return False
    return any(r.id == ROLE_FEDERACJA_ID for r in member.roles)

def is_club_board_or_owner(member: discord.Member, club_tag: str) -> bool:
    """
    Sprawdza czy użytkownik należy do zarządu danego klubu.
    UWAGA: Federacja NIE ma automatycznych uprawnień zarządu – zachowana separacja obowiązków.
    """
    if not member or not club_tag:
        return False

    club = database.get_club(club_tag)
    if not club:
        return False

    # Sprawdzenie roli zarządu z Discorda
    role_board_id = club.get("role_board_id")
    if role_board_id and any(r.id == role_board_id for r in getattr(member, "roles", [])):
        return True

    # Sprawdzenie oznaczonych ID przy rejestracji
    board_ids = club.get("board_ids") or []
    if member.id in board_ids:
        return True

    if member.id == club.get("reprezentant_dc"):
        return True

    return False

def parse_expiry_date(user_input: str) -> str | None:
    if not user_input:
        return None
    user_input = user_input.strip()

    match_days = re.match(r'^(\d+)(\s*(dni|d|day|days))?$', user_input, re.IGNORECASE)
    if match_days:
        days = int(match_days.group(1))
        if days <= 0 or days > 3650:  # max 10 lat
            return None
        try:
            return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        except OverflowError:
            return None

    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(user_input, fmt)
            dt = dt.replace(hour=23, minute=59, second=59)
            if dt < datetime.now():
                return None
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None

def parse_amount(text: str) -> int:
    """
    Parsuje kwotę pieniężną wyłącznie jako czystą liczbę całkowitą.
    Odrzuca teksty z ułamkami i nieznanymi formatami.
    """
    if not text:
        return 0
    t = str(text).strip()
    # Usuń spacje, przecinki jako separator tysięcy (np. "1 500" lub "1,500")
    t = re.sub(r'[\s,]', '', t)
    # Akceptuj tylko czyste liczby całkowite po usunięciu separatorów
    if re.match(r'^\d+$', t):
        return int(t)
    return 0

def validate_amount_input(text: str) -> bool:
    """Sprawdza czy wpisana kwota jest prawidłową liczbą całkowitą."""
    if not text:
        return False
    t = re.sub(r'[\s,]', '', str(text).strip())
    # Dopuść również słowo 'Brak' jako brak klauzuli
    if t.lower() == 'brak':
        return True
    return bool(re.match(r'^\d+$', t))

async def ping_representatives(thread: discord.Thread, target_tag: str, source_tag: str = None):
    ids = []
    c_target = database.get_club(target_tag)
    if c_target:
        if c_target.get("reprezentant_dc"):
            ids.append(c_target["reprezentant_dc"])
        ids.extend(c_target.get("board_ids", []))

    if source_tag:
        c_source = database.get_club(source_tag)
        if c_source:
            if c_source.get("reprezentant_dc"):
                ids.append(c_source["reprezentant_dc"])
            ids.extend(c_source.get("board_ids", []))

    ids = [uid for uid in set(ids) if uid]
    if ids and thread:
        mentions = " ".join([f"<@{uid}>" for uid in ids])
        await thread.send(
            f"🔔 **Wymagana uwaga:** {mentions}\n"
            f"> Użyjcie przycisków powyżej, aby wydać oświadczenie.",
            allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False)
        )

async def send_dm(client: discord.Client, user_id: int, content: str):
    """Bezpieczne wysyłanie DM z obsługą zamkniętych/zablokowanych DM."""
    if not user_id:
        return
    try:
        user = await client.fetch_user(user_id)
        if user:
            await user.send(content)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass

def format_expiry_discord(expires_at: str) -> str:
    """Zwraca timestamp Discorda w formacie relatywnym np. <t:1234567890:R>."""
    if not expires_at:
        return "Brak"
    try:
        dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
        ts = int(dt.timestamp())
        return f"<t:{ts}:R> (<t:{ts}:D>)"
    except Exception:
        return expires_at

def build_squad_bar(count: int, max_count: int) -> str:
    """Zwraca wizualny pasek zapełnienia składu np. [■■□] 2/3."""
    filled = "■" * count
    empty = "□" * (max_count - count)
    label = "Kadra pełna ⛔" if count >= max_count else f"{max_count - count} wolne miejsce{'a' if max_count - count > 1 else ''}"
    return f"`[{filled}{empty}] {count}/{max_count}` · {label}"
