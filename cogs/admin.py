import os
import tempfile
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
import database
from utils.helpers import is_federation
import utils.league_config as league_config


def _is_admin(user) -> bool:
    return getattr(user, 'guild_permissions', None) and user.guild_permissions.administrator or is_federation(user)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Prefix: !reset ────────────────────────────────────────────────────────
    @commands.command(name='reset', aliases=['reset_sezon', 'reset_bazy', 'reset_ligi'])
    async def cmd_reset(self, ctx):
        """Resetuje całą bazę danych ligi na nowy sezon (z zachowaniem konfiguracji /setup)."""
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
        database.reset_database_for_new_season()
        await ctx.reply(embed=_build_reset_embed())

    # ── Prefix: !backup_db ────────────────────────────────────────────────────
    @commands.command(name='backup_db')
    async def cmd_backup_db(self, ctx):
        """Tworzy kopię zapasową bazy SQLite i wysyła plik."""
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień.")
        temp_fd, temp_path = tempfile.mkstemp(suffix=".db", prefix="liga_backup_")
        os.close(temp_fd)
        os.remove(temp_path)
        try:
            database.backup_database_vacuum(temp_path)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            await ctx.reply(
                f"📦 **Backup bazy danych** (liga_backup_{ts}.db)\n> WAL-safe atomic vacuum snapshot",
                file=discord.File(temp_path, filename=f"liga_backup_{ts}.db")
            )
        except Exception as e:
            await ctx.reply(f"❌ Błąd tworzenia kopii: {e}")
        finally:
            if os.path.exists(temp_path):
                try: os.remove(temp_path)
                except Exception: pass

    # ── Prefix: !db_stats ─────────────────────────────────────────────────────
    @commands.command(name='db_stats')
    async def cmd_db_stats(self, ctx):
        """Statystyki pliku bazy SQLite."""
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień.")
        stats = database.get_db_file_stats()
        embed = discord.Embed(title="🗄️ Statystyki bazy SQLite", color=0x2b2d31)
        embed.add_field(name="Rozmiar", value=f"{stats.get('file_size_kb', 0)} KB", inline=True)
        embed.add_field(name="Journal", value=f"{stats.get('journal_mode', '?')}", inline=True)
        embed.add_field(name="FK", value=f"{stats.get('foreign_keys', '?')}", inline=True)
        embed.add_field(name="Rekordy", value=(
            f"> Kluby: {stats.get('clubs', 0)}\n"
            f"> Zawodnicy: {stats.get('players', 0)}\n"
            f"> Wolni agenci: {stats.get('free_agents', 0)}\n"
            f"> Wnioski: {stats.get('applications', 0)}\n"
            f"> Historia: {stats.get('transfer_history', 0)}"
        ), inline=False)
        await ctx.reply(embed=embed)

    # ── Prefix: !przywroc_z_discorda ──────────────────────────────────────────
    @commands.command(name='przywroc_z_discorda', aliases=['odtworz_lige', 'przywroc_baze', 'sync_discord'])
    async def cmd_restore(self, ctx):
        """Automatycznie odtwarza kluby, składy i ustawienia bezpośrednio z ról na serwerze Discord."""
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
        msg = await ctx.reply("🔄 **Rozpoczynam skanowanie serwera Discord i odzyskiwanie danych ligi...**")
        stats = await execute_restore_from_discord(ctx.guild)
        await msg.edit(content=None, embed=_build_restore_embed(stats))

    # ── Slash: /reset ──────────────────────────────────────────────────────────
    @app_commands.command(name='reset', description='[Admin] Resetuj bazę danych ligi na nowy sezon')
    async def slash_reset(self, interaction: discord.Interaction):
        if not _is_admin(interaction.user):
            return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
        database.reset_database_for_new_season()
        await interaction.response.send_message(embed=_build_reset_embed())

    # ── Slash: /przywroc_z_discorda ───────────────────────────────────────────
    @app_commands.command(name='przywroc_z_discorda', description='[Admin] Przywróć wszystkie kluby, graczy i ustawienia bezpośrednio z ról Discorda')
    async def slash_restore(self, interaction: discord.Interaction):
        if not _is_admin(interaction.user):
            return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
        await interaction.response.defer()
        stats = await execute_restore_from_discord(interaction.guild)
        await interaction.followup.send(embed=_build_restore_embed(stats))


async def execute_restore_from_discord(guild: discord.Guild) -> dict:
    import re
    recovered_clubs = []
    recovered_players = []
    recovered_settings = []

    board_pattern = re.compile(r"^(?:⚽[・\s\-]*)?([A-Za-z0-9]{2,5})\s*-\s*Zarząd", re.IGNORECASE)
    player_pattern = re.compile(r"^(?:⚽[・\s\-]*)?([A-Za-z0-9]{2,5})\s*-\s*Zawodnik", re.IGNORECASE)

    club_candidates = {}
    for role in guild.roles:
        m_board = board_pattern.match(role.name)
        if m_board:
            tag = m_board.group(1).upper()
            club_candidates.setdefault(tag, {})["board_role"] = role
            continue
        m_player = player_pattern.match(role.name)
        if m_player:
            tag = m_player.group(1).upper()
            club_candidates.setdefault(tag, {})["player_role"] = role

    for tag, r_dict in club_candidates.items():
        r_board = r_dict.get("board_role")
        r_player = r_dict.get("player_role")
        if not r_board or not r_player:
            continue

        board_members = [m for m in guild.members if r_board in m.roles]
        rep_dc = board_members[0].id if board_members else None
        board_ids = [m.id for m in board_members]
        founder_txt = f"<@{rep_dc}>" if rep_dc else "Brak"
        board_txt = ", ".join(f"<@{uid}>" for uid in board_ids) if board_ids else "Brak"

        existing = database.get_club(tag)
        c_name = existing.get("name") if existing else f"Klub {tag}"

        database.add_club(
            tag=tag,
            name=c_name,
            role_board_id=r_board.id,
            role_player_id=r_player.id,
            reprezentant_dc=rep_dc,
            founder_txt=founder_txt,
            board_txt=board_txt,
            board_ids=board_ids
        )
        recovered_clubs.append({
            "tag": tag,
            "name": c_name,
            "board_count": len(board_members)
        })

        club_players = [m for m in guild.members if r_player in m.roles]
        for p in club_players:
            database.add_or_update_player(
                name=p.display_name,
                discord_id=p.id,
                club_tag=tag,
                parent_club_tag=tag,
                clause="Brak",
                contract_type="ODZYSKANY",
                expires_at="30.06.2027"
            )
            recovered_players.append({
                "name": p.display_name,
                "discord_id": p.id,
                "club_tag": tag
            })

    # Odnajdź brakujące konfiguracje
    if not league_config.channel_forum_id():
        for ch in guild.channels:
            if ch.type == discord.ChannelType.forum and any(w in ch.name.lower() for w in ["wniosk", "transfer", "biuro"]):
                league_config.set_config("cfg_channel_forum", str(ch.id))
                recovered_settings.append(f"Forum: #{ch.name}")
                break

    if not league_config.channel_komunikaty_id():
        for ch in guild.text_channels:
            if any(w in ch.name.lower() for w in ["komunikat", "ogloszen", "news"]):
                league_config.set_config("cfg_channel_komunikaty", str(ch.id))
                recovered_settings.append(f"Komunikaty: #{ch.name}")
                break

    if not league_config.role_federacja_id():
        for r in guild.roles:
            if any(w in r.name.lower() for w in ["federacj", "zarząd federacji", "fss"]):
                league_config.set_config("cfg_role_federacja", str(r.id))
                recovered_settings.append(f"Rola Federacji: @{r.name}")
                break

    database.sync_persistent_backup()

    return {
        "clubs": recovered_clubs,
        "players": recovered_players,
        "settings": recovered_settings
    }


def _build_restore_embed(stats: dict) -> discord.Embed:
    org_name = league_config.league_name()
    embed = discord.Embed(
        title="♻️ Baza Danych Przywrócona z Discorda",
        description="> Przeskanowano role serwera i pomyślnie odtworzono strukturę ligi w SQLite.",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )

    clubs = stats.get("clubs", [])
    if clubs:
        c_lines = [f"> • **{c['tag']}** ({c['name']}) · Zarząd: {c['board_count']} os." for c in clubs]
        embed.add_field(name=f"🏛️ Odzyskane Kluby ({len(clubs)})", value="\n".join(c_lines[:15]), inline=False)
    else:
        embed.add_field(name="🏛️ Odzyskane Kluby", value="> Brak ról klubowych o schemacie `⚽・{TAG} - Zarząd`", inline=False)

    players = stats.get("players", [])
    if players:
        p_lines = [f"> • **{p['name']}** ➔ `{p['club_tag']}`" for p in players]
        embed.add_field(name=f"👤 Odzyskani Zawodnicy ({len(players)})", value="\n".join(p_lines[:20]), inline=False)
    else:
        embed.add_field(name="👤 Odzyskani Zawodnicy", value="> Brak graczy z rolami `⚽・{TAG} - Zawodnik`", inline=False)

    settings = stats.get("settings", [])
    if settings:
        embed.add_field(name="⚙️ Zsynchronizowane Ustawienia", value="\n".join(f"> • {s}" for s in settings), inline=False)

    embed.add_field(name="🛡️ Trwałość Bazy", value="> Dane zostały zsynchronizowane z plikiem `liga_persistent.db`.", inline=False)
    embed.set_footer(text=f"{org_name} • Przywracanie")
    return embed


def _build_reset_embed() -> discord.Embed:
    org_name = league_config.league_name()
    mx = league_config.max_players()
    embed = discord.Embed(
        title="🏆 Liga Zresetowana",
        description="> Baza danych wyczyszczona z powodzeniem. Można rejestrować kluby i zawodników.",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="📋 Co wyczyszczono", value=(
        "> • `clubs` · `players` · `applications`\n"
        "> • `transfer_history` · `free_agents`\n"
        "> • Licznik ticketów → `#001`\n"
        "> • Rynek transferowy → **OTWARTY**"
    ), inline=False)
    embed.add_field(name="⚙️ Zachowana konfiguracja (/setup)", value=(
        f"> • Max graczy w klubie: **{mx}**\n"
        "> • ID kanałów i ról: **Bez zmian**\n"
        f"> • Organizacja: **{org_name}**"
    ), inline=False)
    embed.set_footer(text=f"{org_name} • {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
