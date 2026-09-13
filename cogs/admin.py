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
    return (getattr(user, 'guild_permissions', None) and user.guild_permissions.administrator) or is_federation(user)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._register_slash_commands()

    def _register_slash_commands(self):
        reset_group = app_commands.Group(name="reset", description="[Admin] Narzędzia resetowania bazy danych i ligi")

        @reset_group.command(name="wszystko", description="[Admin] Usuwa absolutnie wszystko z bazy, łącznie z panelem /setup")
        async def reset_wszystko(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            database.reset_all(full_reset_including_setup=True)
            await interaction.response.send_message(embed=_build_reset_embed("wszystko"))

        @reset_group.command(name="kluby", description="[Admin] Resetuje kluby, powiązane kontrakty i wnioski (zachowuje /setup i giełdę)")
        async def reset_kluby(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            database.reset_clubs()
            await interaction.response.send_message(embed=_build_reset_embed("kluby"))

        @reset_group.command(name="kontrakty", description="[Admin] Resetuje kontrakty zawodników i wnioski (zachowuje kluby i /setup)")
        async def reset_kontrakty(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            database.reset_contracts()
            await interaction.response.send_message(embed=_build_reset_embed("kontrakty"))

        @reset_group.command(name="wnioski", description="[Admin] Czyści wnioski transferowe i resetuje licznik ticketów do #001")
        async def reset_wnioski(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            database.reset_applications()
            await interaction.response.send_message(embed=_build_reset_embed("wnioski"))

        @reset_group.command(name="rynek", description="[Admin] Otwiera rynek, kasuje zaplanowany harmonogram i czyści giełdę graczy")
        async def reset_rynek(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            database.reset_market()
            await interaction.response.send_message(embed=_build_reset_embed("rynek"))

        @reset_group.command(name="setup", description="[Admin] Przywraca domyślne ustawienia panelu /setup (zachowuje kluby i graczy)")
        async def reset_setup(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            database.reset_setup()
            await interaction.response.send_message(embed=_build_reset_embed("setup"))

        self.reset_slash_group = reset_group

    async def cog_load(self):
        self.bot.tree.add_command(self.reset_slash_group)

    async def cog_unload(self):
        self.bot.tree.remove_command("reset")

    # ── Prefix: !reset [zakres] ───────────────────────────────────────────────
    @commands.command(name='reset', aliases=['reset_sezon', 'reset_bazy', 'reset_ligi'])
    async def cmd_reset(self, ctx, zakres: str = "wszystko"):
        """
        Resetuje wybrane dane ligi:
        !reset wszystko  -> Czyści absolutnie wszystko (łącznie z konfiguracją /setup)
        !reset kluby     -> Czyści kluby, powiązane kontrakty i wnioski (zachowuje /setup)
        !reset kontrakty -> Czyści kontrakty i zawodników (zachowuje kluby i /setup)
        !reset wnioski   -> Czyści tylko wnioski i resetuje licznik ticketów #001
        !reset rynek     -> Otwiera rynek, usuwa harmonogram i czyści giełdę
        !reset setup     -> Przywraca domyślne ustawienia /setup (zachowuje kluby/graczy)
        """
        if not _is_admin(ctx.author):
            return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")

        z = zakres.lower().strip()
        if z in ("wszystko", "all", "calosc"):
            database.reset_all(full_reset_including_setup=True)
            await ctx.reply(embed=_build_reset_embed("wszystko"))
        elif z in ("kluby", "clubs", "druzyny"):
            database.reset_clubs()
            await ctx.reply(embed=_build_reset_embed("kluby"))
        elif z in ("kontrakty", "zawodnicy", "gracze", "contracts", "players"):
            database.reset_contracts()
            await ctx.reply(embed=_build_reset_embed("kontrakty"))
        elif z in ("wnioski", "tickety", "applications"):
            database.reset_applications()
            await ctx.reply(embed=_build_reset_embed("wnioski"))
        elif z in ("rynek", "market", "gielda"):
            database.reset_market()
            await ctx.reply(embed=_build_reset_embed("rynek"))
        elif z in ("setup", "panel", "config"):
            database.reset_setup()
            await ctx.reply(embed=_build_reset_embed("setup"))
        else:
            await ctx.reply(
                "❌ Nieznany zakres resetu!\n"
                "Dostępne opcje: `!reset wszystko`, `!reset kluby`, `!reset kontrakty`, "
                "`!reset wnioski`, `!reset rynek`, `!reset setup`."
            )

    # ── Prefix: !backup_db ────────────────────────────────────────────────────
    @commands.command(name='backup_db')
    async def cmd_backup_db(self, ctx):
        """Tworzy kopię zapasową bazy SQLite i wysyła plik."""
        if not _is_admin(ctx.author):
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
        if not _is_admin(ctx.author):
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


def _build_reset_embed(zakres: str) -> discord.Embed:
    org_name = league_config.league_name()
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    if zakres == "wszystko":
        embed = discord.Embed(
            title="💥 Pełny Reset Ligi (Wszystko)",
            description="> Baza danych została całkowicie wyczyszczona łącznie z panelem `/setup`.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="📋 Co wyczyszczono", value=(
            "> • `clubs` (wszystkie kluby i zarządy)\n"
            "> • `players` (wszystkie kontrakty i gracze)\n"
            "> • `applications` oraz licznik ticketów → `#001`\n"
            "> • `transfer_history` oraz `free_agents`\n"
            "> • **Konfiguracja `/setup`** (przywrócono domyślne)"
        ), inline=False)
        embed.add_field(name="🔄 Rynek Transferowy", value="> Ustawiono jako **OTWARTY**", inline=False)

    elif zakres == "kluby":
        embed = discord.Embed(
            title="🏛️ Reset Klubów",
            description="> Pomyślnie zresetowano wszystkie kluby i powiązane z nimi kontrakty.",
            color=0xe67e22,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="📋 Co wyczyszczono", value=(
            "> • `clubs` (wszystkie kluby)\n"
            "> • `players` (kontrakty zawodników w klubach)\n"
            "> • `applications` (wszystkie wnioski)\n"
            "> • `transfer_history` (historia transferów)\n"
            "> • Licznik ticketów → `#001`"
        ), inline=False)
        embed.add_field(name="🛡️ Zachowano", value=(
            "> • Konfiguracja panelu `/setup` (**Nienaruszona**)\n"
            "> • Giełda wolnych agentów (**Nienaruszona**)"
        ), inline=False)

    elif zakres == "kontrakty":
        embed = discord.Embed(
            title="👤 Reset Kontraktów i Zawodników",
            description="> Pomyślnie wyczyszczono kontrakty, zawodników oraz giełdę wolnych agentów.",
            color=0xf39c12,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="📋 Co wyczyszczono", value=(
            "> • `players` (wszystkie aktywne kontrakty)\n"
            "> • `free_agents` (giełda wolnych agentów)\n"
            "> • `applications` oraz licznik ticketów → `#001`\n"
            "> • `transfer_history`"
        ), inline=False)
        embed.add_field(name="🛡️ Zachowano", value=(
            "> • Wszystkie zarejestrowane kluby i ich zarządy (**Nienaruszone**)\n"
            "> • Konfiguracja panelu `/setup` (**Nienaruszona**)"
        ), inline=False)

    elif zakres == "wnioski":
        embed = discord.Embed(
            title="📄 Reset Wniosków Transferowych",
            description="> Wyczyszczono historię wniosków oraz zresetowano numerację ticketów.",
            color=0x3498db,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="📋 Co wyczyszczono", value=(
            "> • `applications` (tabela wniosków)\n"
            "> • Licznik ticketów zresetowany do: `#001`"
        ), inline=False)
        embed.add_field(name="🛡️ Zachowano", value=(
            "> • Kluby i zawodnicy (**Bez zmian**)\n"
            "> • Ustawienia panelu `/setup` (**Bez zmian**)"
        ), inline=False)

    elif zakres == "rynek":
        embed = discord.Embed(
            title="🔄 Reset Rynku Transferowego",
            description="> Zresetowano status rynku oraz wyczyszczono giełdę graczy.",
            color=0x2ecc71,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="📋 Zmiany", value=(
            "> • Status rynku: **OTWARTY**\n"
            "> • Zaplanowany harmonogram: **Usunięty**\n"
            "> • Giełda wolnych agentów: **Wyczyszczona**"
        ), inline=False)
        embed.add_field(name="🛡️ Zachowano", value=(
            "> • Wszystkie kluby i kontrakty zawodników (**Bez zmian**)\n"
            "> • Ustawienia panelu `/setup` (**Bez zmian**)"
        ), inline=False)

    elif zakres == "setup":
        embed = discord.Embed(
            title="⚙️ Reset Konfiguracji /setup",
            description="> Przywrócono domyślne ustawienia panelu administracyjnego.",
            color=0x9b59b6,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="📋 Zmiany", value=(
            "> • Usunięto niestandardowe ID kanałów i ról\n"
            "> • Przywrócono domyślny limit: **3 graczy**\n"
            "> • Przywrócono domyślne etykiety ligi"
        ), inline=False)
        embed.add_field(name="🛡️ Zachowano", value=(
            "> • Wszystkie kluby i zarządy (**Nienaruszone**)\n"
            "> • Wszyscy zawodnicy i kontrakty (**Nienaruszone**)"
        ), inline=False)

    embed.set_footer(text=f"{org_name} • {now_str}")
    return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
