import asyncio
import traceback
from datetime import datetime
import discord
from discord import ui
import database
from config import ROLE_FEDERACJA_ID, CHANNEL_FORUM_ID, MAX_PLAYERS_PER_CLUB
import utils.league_config as league_config

from utils.helpers import (
    clean_tag, is_valid_tag, extract_ids, parse_expiry_date,
    parse_amount, validate_amount_input, is_club_board_or_owner,
    ping_representatives, send_dm, has_open_ticket, safe_thread_name, get_now_warsaw,
    resolve_player_identity, clean_player_name, is_federation, get_komunikaty_channel
)
from views.confirmation import WniosekConfirmView
from views.application_view import ForumApplicationView


async def _create_ticket_channel(guild: discord.Guild, user: discord.Member, prefix: str) -> discord.TextChannel:
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    rola_fed = guild.get_role(league_config.role_federacja_id() or ROLE_FEDERACJA_ID)
    if rola_fed:
        overwrites[rola_fed] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    ticket_id = database.get_next_ticket_id()
    return await guild.create_text_channel(f"{prefix}-{ticket_id}", overwrites=overwrites)


async def _safe_delete_channel(kanal):
    if not kanal: return
    try:
        await kanal.delete(reason="Ticket zakończony")
    except Exception:
        pass


async def _zadaj_pytanie(kanal, uzytkownik, pytanie, client) -> str:
    try:
        await kanal.send(embed=discord.Embed(description=f"❓ {pytanie}", color=0x3498db))
    except Exception:
        raise TimeoutError("Kanał został zamknięty")

    def check(m):
        return m.author == uzytkownik and m.channel == kanal

    try:
        msg = await client.wait_for('message', check=check, timeout=900.0)
        return msg.content.strip()
    except asyncio.TimeoutError:
        try:
            await kanal.send(embed=discord.Embed(
                title="⏳ Upłynął czas",
                description="**Minęło 15 minut braku aktywności.** Wniosek anulowany.",
                color=0xf39c12
            ))
            await asyncio.sleep(3)
        except Exception:
            pass
        await _safe_delete_channel(kanal)
        raise TimeoutError("Timeout ankiety")


async def _send_forum_application(guild, kanal, embed, thread_name, app_id,
                                   ping_target=None, ping_source=None):
    forum = guild.get_channel(league_config.channel_forum_id() or CHANNEL_FORUM_ID)
    v = ForumApplicationView(app_id)
    safe_name = safe_thread_name(thread_name)
    thread = await forum.create_thread(name=safe_name, embed=embed, view=v)
    database.set_application_message(app_id, thread.thread.id, thread.message.id)
    if ping_target or ping_source:
        await ping_representatives(thread.thread, ping_target, ping_source)
    await kanal.send(embed=discord.Embed(description="✅ Wniosek wysłany na forum! Zamykam kanał...", color=0x2ecc71))
    await asyncio.sleep(2)
    try:
        await _safe_delete_channel(kanal)
    except Exception:
        pass
    return thread.thread


def _check_spam(guild, user, interaction) -> bool:
    """Zwraca True jeśli użytkownik ma już otwarty ticket (blokada spamu)."""
    if has_open_ticket(guild, user.id):
        return True
    return False


