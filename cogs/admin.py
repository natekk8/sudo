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

    # ── Slash: /reset ──────────────────────────────────────────────────────────
    @app_commands.command(name='reset', description='[Admin] Resetuj bazę danych ligi na nowy sezon')
    async def slash_reset(self, interaction: discord.Interaction):
        if not _is_admin(interaction.user):
            return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
        database.reset_database_for_new_season()
        await interaction.response.send_message(embed=_build_reset_embed())


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
