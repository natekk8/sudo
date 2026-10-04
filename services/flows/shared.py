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
    resolve_player_identity, clean_player_name, is_federation, get_komunikaty_channel,
    get_or_fetch_member, get_bot
)
from views.confirmation import WniosekConfirmView
from views.application_view import ForumApplicationView


class TicketControlView(ui.View):
    """Widok z przyciskiem umożliwiającym natychmiastowe zamknięcie/anulowanie otwartego ticketu."""
    def __init__(self, creator_id: int):
        super().__init__(timeout=None)
        self.creator_id = creator_id

    @ui.button(label="🔒 Zamknij ticket", style=discord.ButtonStyle.danger, custom_id="ticket_abort_btn")
    async def btn_close(self, interaction: discord.Interaction, button: ui.Button):
        is_allowed = (interaction.user.id == self.creator_id or 
                      is_federation(interaction.user) or 
                      (getattr(interaction.user, "guild_permissions", None) and interaction.user.guild_permissions.administrator))
        if not is_allowed:
            return await interaction.response.send_message("❌ Tylko twórca ticketa lub Zarząd Federacji może zamknąć ten kanał.", ephemeral=True)
        await interaction.response.send_message("🔒 Zamykam ticket na żądanie...", ephemeral=True)
        await asyncio.sleep(1)
        await _safe_delete_channel(interaction.channel)


async def _create_ticket_channel(guild: discord.Guild, user: discord.Member, prefix: str) -> discord.TextChannel:
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    rola_fed = guild.get_role(league_config.role_federacja_id() or ROLE_FEDERACJA_ID)
    if rola_fed:
        overwrites[rola_fed] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    category = None
    if guild and hasattr(guild, "categories"):
        category = discord.utils.get(guild.categories, name="TICKETY FSS")
        if not category and hasattr(guild, "create_category"):
            try:
                category = await guild.create_category(
                    "TICKETY FSS",
                    overwrites={
                        guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
                        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
                    }
                )
            except Exception:
                category = None

    ticket_id = database.get_next_ticket_id()
    kwargs = {"overwrites": overwrites}
    if category:
        kwargs["category"] = category
    channel = await guild.create_text_channel(f"{prefix}-{ticket_id}", **kwargs)

    try:
        welcome_embed = discord.Embed(
            title=f"🎫 Ticket #{ticket_id}",
            description=f"Witaj {user.mention}! Zaraz rozpocznie się procedura wniosku.\n"
                        f"> W dowolnej chwili możesz kliknąć poniższy przycisk, aby anulować wniosek i zamknąć ticket.",
            color=0x3d5a80
        )
        await channel.send(embed=welcome_embed, view=TicketControlView(user.id))
    except Exception:
        pass

    return channel


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


async def _is_fed_staff(guild: discord.Guild, user_id: int) -> bool:
    """Zarząd Federacji lub administrator serwera."""
    if not guild or not user_id:
        return False
    member = await get_or_fetch_member(guild, user_id)
    if not member:
        return False
    return bool(is_federation(member) or
                (getattr(member, "guild_permissions", None) and member.guild_permissions.administrator))


async def _send_forum_application(guild, kanal, embed, thread_name, app_id,
                                   ping_target=None, ping_source=None, client=None):
    forum = guild.get_channel(league_config.channel_forum_id() or CHANNEL_FORUM_ID)
    v = ForumApplicationView(app_id)
    safe_name = safe_thread_name(thread_name)
    thread = await forum.create_thread(name=safe_name, embed=embed, view=v)
    database.set_application_message(app_id, thread.thread.id, thread.message.id)

    app = database.get_application(app_id) or {}
    fed_user_id = app.get("applicant_id")
    auto_done = False
    if await _is_fed_staff(guild, fed_user_id):
        # Wniosek składa Federacja → od razu zatwierdzony, bez zgód stron.
        client = client or get_bot()
        fed_member = await get_or_fetch_member(guild, fed_user_id)
        if client and fed_member:
            auto_done = await v.fed_auto_accept(client, guild, thread, fed_member)

    if not auto_done:
        if ping_target or ping_source:
            await ping_representatives(thread.thread, ping_target, ping_source)
        player_dc = app.get("player_discord_id")
        if player_dc:
            try:
                await thread.thread.send(f"👤 <@{player_dc}> – wpłynął wniosek z Twoim udziałem. Zapoznaj się z powyższymi warunkami i kliknij przycisk zgody.")
            except Exception:
                pass

    if auto_done:
        msg = "✅ Wniosek złożony przez Zarząd Federacji został **od razu zatwierdzony**. Zamykam kanał..."
    else:
        msg = "✅ Wniosek wysłany na forum! Zamykam kanał..."
    await kanal.send(embed=discord.Embed(description=msg, color=0x2ecc71))
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


