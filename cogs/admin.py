import os
import csv
import io
import tempfile
import asyncio
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
import database
from utils.helpers import is_federation
import utils.league_config as league_config


def _is_admin(user) -> bool:
    return (getattr(user, 'guild_permissions', None) and user.guild_permissions.administrator) or is_federation(user)


def _generate_csv(data: list[dict], fieldnames: list[str]) -> io.BytesIO:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    for row in data:
        writer.writerow(row)
    bio = io.BytesIO(buf.getvalue().encode('utf-8-sig'))
    bio.seek(0)
    return bio


def _get_export_files(zakres: str) -> list[discord.File]:
    files = []
    z = (zakres or "wszystko").lower().strip()
    now_str = datetime.now().strftime("%Y%m%d_%H%M")

    if z in ("wszystko", "all", "gracze", "players", "zawodnicy"):
        players = database.get_all_players()
        p_bio = _generate_csv(players, [
            "name", "discord_id", "club_tag", "parent_club_tag", "contract_type",
            "clause", "expires_at", "is_overflow", "slot_deadline"
        ])
        files.append(discord.File(p_bio, filename=f"fss_zawodnicy_{now_str}.csv"))

    if z in ("wszystko", "all", "kluby", "clubs"):
        clubs = database.get_all_clubs()
        c_bio = _generate_csv(clubs, [
            "tag", "name", "reprezentant_dc", "role_board_id", "role_player_id",
            "founder_txt", "board_txt"
        ])
        files.append(discord.File(c_bio, filename=f"fss_kluby_{now_str}.csv"))

    if z in ("wszystko", "all", "historia", "history"):
        history = database.get_all_transfer_history()
        h_bio = _generate_csv(history, [
            "id", "player_name", "player_discord_id", "from_club", "to_club",
            "transfer_type", "amount", "date"
        ])
        files.append(discord.File(h_bio, filename=f"fss_historia_{now_str}.csv"))

    if z in ("wszystko", "all", "lista_transferowa", "transfer_list", "rynek"):
        tlist = database.get_transfer_list()
        t_bio = _generate_csv(tlist, [
            "player_name", "discord_id", "club_tag", "price", "created_at"
        ])
        files.append(discord.File(t_bio, filename=f"fss_lista_transferowa_{now_str}.csv"))

    return files


class ResetConfirmView(discord.ui.View):
    def __init__(self, user_id: int, scope: str, reset_func, is_slash: bool = True):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.scope = scope
        self.reset_func = reset_func
        self.is_slash = is_slash
        self.message = None

    @discord.ui.button(label="⚠️ Potwierdź reset", style=discord.ButtonStyle.danger, custom_id="btn_confirm_reset")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Tylko osoba wywołująca komendę może zatwierdzić reset.", ephemeral=True)
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.defer()
        snapshot = await asyncio.to_thread(self.reset_func)
        try:
            from utils.helpers import send_audit_log
            await send_audit_log(
                client=interaction.client,
                guild=interaction.guild,
                title=f"RESET BAZY: {self.scope.upper()}",
                description=f"Użytkownik {interaction.user.mention} zatwierdził reset obszaru **{self.scope}**.",
                color=0x992d22,
                fields=[
                    ("Administrator", f"{interaction.user} (`{interaction.user.id}`)", True),
                    ("Zakres", self.scope, True),
                    ("Snapshot bazy", str(snapshot or "Brak"), False)
                ]
            )
        except Exception as e:
            print(f"[Admin] Błąd logowania resetu do audytu: {e}")
        embed = _build_reset_embed(self.scope)
        if snapshot:
            embed.set_footer(text=f"Bezpieczny snapshot: {snapshot}")
        if self.is_slash:
            await interaction.edit_original_response(content=None, embed=embed, view=None)
        else:
            if self.message:
                await self.message.edit(content=None, embed=embed, view=None)

    @discord.ui.button(label="Anuluj", style=discord.ButtonStyle.secondary, custom_id="btn_cancel_reset")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
        self.stop()
        for item in self.children:
            item.disabled = True
        if self.is_slash:
            await interaction.response.edit_message(content="🛑 **Operacja resetu została anulowana.** Żadne dane nie zostały zmienione.", embed=None, view=None)
        else:
            await interaction.response.edit_message(content="🛑 **Operacja resetu została anulowana.** Żadne dane nie zostały zmienione.", embed=None, view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(content="⏳ **Czas na potwierdzenie minął (30s).** Reset został anulowany.", embed=None, view=None)
        except Exception:
            pass


async def _ask_reset_confirmation(interaction: discord.Interaction, scope: str, reset_func):
    desc = {
        "wszystko": "Zamierzasz **całkowicie usunąć całą bazę ligi** (kluby, graczy, wnioski, rynek, konfigurację /setup).",
        "kluby": "Zamierzasz usunąć **wszystkie kluby, powiązane kontrakty i wnioski**.",
        "kontrakty": "Zamierzasz usunąć **wszystkie kontrakty i zawodników**.",
        "wnioski": "Zamierzasz usunąć **wszystkie wnioski transferowe** i zresetować licznik ticketów.",
        "rynek": "Zamierzasz **zresetować rynek transferowy i wyczyścić giełdę graczy**.",
        "setup": "Zamierzasz **przywrócić domyślne ustawienia panelu /setup**."
    }.get(scope, f"Zamierzasz wykonać reset: `{scope}`.")

    embed = discord.Embed(
        title="⚠️ Potwierdzenie Resetu Danych",
        description=f"{desc}\n\n"
                    f"> **Przed usunięciem zostanie wykonany automatyczny snapshot bazy.**\n"
                    f"> Kliknij poniższy przycisk w ciągu **30 sekund**, aby potwierdzić.",
        color=0xe74c3c
    )
    view = ResetConfirmView(interaction.user.id, scope, reset_func, is_slash=True)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    view.message = await interaction.original_response()


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
            await _ask_reset_confirmation(interaction, "wszystko", lambda: database.reset_all(full_reset_including_setup=True))

        @reset_group.command(name="kluby", description="[Admin] Resetuje kluby, powiązane kontrakty i wnioski (zachowuje /setup i giełdę)")
        async def reset_kluby(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            await _ask_reset_confirmation(interaction, "kluby", database.reset_clubs)

        @reset_group.command(name="kontrakty", description="[Admin] Resetuje kontrakty zawodników i wnioski (zachowuje kluby i /setup)")
        async def reset_kontrakty(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            await _ask_reset_confirmation(interaction, "kontrakty", database.reset_contracts)

        @reset_group.command(name="wnioski", description="[Admin] Czyści wnioski transferowe i resetuje licznik ticketów do #001")
        async def reset_wnioski(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            await _ask_reset_confirmation(interaction, "wnioski", database.reset_applications)

        @reset_group.command(name="rynek", description="[Admin] Otwiera rynek, kasuje zaplanowany harmonogram i czyści giełdę graczy")
        async def reset_rynek(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            await _ask_reset_confirmation(interaction, "rynek", database.reset_market)

        @reset_group.command(name="setup", description="[Admin] Przywraca domyślne ustawienia panelu /setup (zachowuje kluby i graczy)")
        async def reset_setup(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            await _ask_reset_confirmation(interaction, "setup", database.reset_setup)

        @app_commands.command(name="eksport", description="[Admin] Eksportuj dane ligi (zawodnicy, kluby, historia) do plików CSV (Excel)")
        @app_commands.describe(zakres="Zakres danych do wyeksportowania")
        @app_commands.choices(zakres=[
            app_commands.Choice(name="Wszystkie tabele (paczka CSV)", value="wszystko"),
            app_commands.Choice(name="Zawodnicy (zawodnicy.csv)", value="gracze"),
            app_commands.Choice(name="Kluby (kluby.csv)", value="kluby"),
            app_commands.Choice(name="Historia Transferów (historia.csv)", value="historia"),
            app_commands.Choice(name="Lista Transferowa (lista_transferowa.csv)", value="lista_transferowa"),
        ])
        async def slash_eksport(interaction: discord.Interaction, zakres: app_commands.Choice[str]):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień. Wymagany Zarząd Federacji / Administrator.", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            files = _get_export_files(zakres.value)
            if not files:
                return await interaction.followup.send("❌ Brak danych do wyeksportowania w wybranej kategorii.", ephemeral=True)
            embed = discord.Embed(
                title="📦 Eksport Danych Ligi (FSS)",
                description=f"> Wygenerowano pliki dla kategorii: **{zakres.name}**.\n> Pliki CSV zakodowano w standardzie `UTF-8 BOM` (zgodność z programem MS Excel).",
                color=0x2ecc71
            )
            embed.set_footer(text=f"Eksport wygenerowany przez {interaction.user}")
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)

        self.reset_slash_group = reset_group
        self.eksport_slash_cmd = slash_eksport

    async def cog_load(self):
        self.bot.tree.add_command(self.reset_slash_group)
        self.bot.tree.add_command(self.eksport_slash_cmd)

    async def cog_unload(self):
        self.bot.tree.remove_command("reset")
        self.bot.tree.remove_command("eksport")

    # ── Prefix: !eksport [zakres] ─────────────────────────────────────────────
    @commands.command(name='eksport', aliases=['export', 'pobierz_dane'])
    async def cmd_eksport(self, ctx, zakres: str = "wszystko"):
        """
        Eksportuje dane ligi do plików CSV (Excel):
        !eksport wszystko          -> Eksportuje graczy, kluby, historię i rynek
        !eksport gracze            -> Eksportuje tylko zawodników
        !eksport kluby             -> Eksportuje tylko kluby
        !eksport historia          -> Eksportuje tylko historię transferów
        !eksport lista_transferowa -> Eksportuje listę transferową
        """
        if not _is_admin(ctx.author):
            return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
        files = _get_export_files(zakres)
        if not files:
            return await ctx.reply("❌ Brak danych do wyeksportowania lub nieprawidłowy zakres.")
        embed = discord.Embed(
            title="📦 Eksport Danych Ligi (FSS)",
            description=f"> Pomyślnie wygenerowano pliki CSV dla zakresu: **{zakres}**.\n> Zgodność ze standardem Microsoft Excel (UTF-8 BOM).",
            color=0x2ecc71
        )
        embed.set_footer(text=f"Wygenerowano przez {ctx.author}")
        await ctx.reply(embed=embed, files=files)

    # ── Prefix: !reset [zakres] ───────────────────────────────────────────────
    @commands.command(name='reset', aliases=['reset_sezon', 'reset_bazy', 'reset_ligi'])
    async def cmd_reset(self, ctx, zakres: str = "wszystko"):
        """
        Resetuje wybrane dane ligi (wymaga potwierdzenia przyciskiem):
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
        scope_map = {
            "wszystko": ("wszystko", lambda: database.reset_all(full_reset_including_setup=True)),
            "all": ("wszystko", lambda: database.reset_all(full_reset_including_setup=True)),
            "calosc": ("wszystko", lambda: database.reset_all(full_reset_including_setup=True)),
            "kluby": ("kluby", database.reset_clubs),
            "clubs": ("kluby", database.reset_clubs),
            "druzyny": ("kluby", database.reset_clubs),
            "kontrakty": ("kontrakty", database.reset_contracts),
            "zawodnicy": ("kontrakty", database.reset_contracts),
            "gracze": ("kontrakty", database.reset_contracts),
            "contracts": ("kontrakty", database.reset_contracts),
            "players": ("kontrakty", database.reset_contracts),
            "wnioski": ("wnioski", database.reset_applications),
            "tickety": ("wnioski", database.reset_applications),
            "applications": ("wnioski", database.reset_applications),
            "rynek": ("rynek", database.reset_market),
            "market": ("rynek", database.reset_market),
            "gielda": ("rynek", database.reset_market),
            "setup": ("setup", database.reset_setup),
            "panel": ("setup", database.reset_setup),
            "config": ("setup", database.reset_setup),
        }

        if z not in scope_map:
            return await ctx.reply(
                "❌ Nieznany zakres resetu!\n"
                "Dostępne opcje: `!reset wszystko`, `!reset kluby`, `!reset kontrakty`, "
                "`!reset wnioski`, `!reset rynek`, `!reset setup`."
            )

        scope, func = scope_map[z]
        embed = discord.Embed(
            title="⚠️ Potwierdzenie Resetu Danych",
            description=f"Zamierzasz zresetować: **{scope}**.\n\n"
                        f"> Kliknij poniższy przycisk w ciągu **30 sekund**, aby potwierdzić.\n"
                        f"> Przed usunięciem zostanie utworzony automatyczny snapshot bazy.",
            color=0xe74c3c
        )
        view = ResetConfirmView(ctx.author.id, scope, func, is_slash=False)
        msg = await ctx.reply(embed=embed, view=view)
        view.message = msg

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
            f"> Lista transferowa: {stats.get('transfer_list', 0)}\n"
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
            "> • `transfer_list` (lista transferowa)\n"
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
            "> • `transfer_list` (lista transferowa klubów)\n"
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
            "> • `transfer_list` (lista transferowa)\n"
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
            description="> Zresetowano status rynku oraz wyczyszczono giełdę i listę transferową.",
            color=0x2ecc71,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="📋 Zmiany", value=(
            "> • Status rynku: **OTWARTY**\n"
            "> • Zaplanowany harmonogram: **Usunięty**\n"
            "> • Lista transferowa: **Wyczyszczona**\n"
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
