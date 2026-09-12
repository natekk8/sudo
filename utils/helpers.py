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
    if not member or not club_tag:
        return False
    if is_federation(member):
        return True

    club = database.get_club(club_tag)
    if not club:
        return False

    # Sprawdzenie roli zarządu
    role_board_id = club.get("role_board_id")
    if role_board_id and any(r.id == role_board_id for r in getattr(member, "roles", [])):
        return True

    # Sprawdzenie oznaczonych ID założyciela/zarządu
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
        if days <= 0:
            return None
        return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

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
    if not text:
        return 0
    digits = "".join(filter(str.isdigit, str(text)))
    return int(digits) if digits else 0

async def ping_representatives(thread: discord.Thread, target_tag: str, source_tag: str = None):
    ids = []
    c_target = database.get_club(target_tag)
    if c_target:
        if c_target.get("reprezentant_dc"):
            ids.append(c_target.get("reprezentant_dc"))
        ids.extend(c_target.get("board_ids", []))

    if source_tag:
        c_source = database.get_club(source_tag)
        if c_source:
            if c_source.get("reprezentant_dc"):
                ids.append(c_source.get("reprezentant_dc"))
            ids.extend(c_source.get("board_ids", []))

    ids = [uid for uid in set(ids) if uid]
    if ids and thread:
        mentions = " ".join([f"<@{uid}>" for uid in ids])
        await thread.send(f"🔔 **Wymagana uwaga:** {mentions}\n> Użyjcie przycisków powyżej, aby wydać oświadczenie.")
