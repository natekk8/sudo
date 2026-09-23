"""
cogs/setup_cog.py
=================
Unified /setup slash command z nested subgroupami i interaktywnym UI.

Struktura slash commands:
  /setup                           → panel konfiguracji z przyciskami (ephemeral)
  /setup liga max_graczy <n>       → zmiana limitu graczy
  /setup liga sezon <label>        → zmiana oznaczenia sezonu
  /setup liga nazwa <text>         → zmiana nazwy ligi w footerach
  /setup kanal forum <id>          → kanał forum wniosków
  /setup kanal komunikaty <id>     → kanał oficjalnych komunikatów
  /setup rola federacja <id>       → rola Zarządu Federacji
  /setup rola wzorzec <id>         → wzorzec roli gracza
  /setup rynek otworz              → natychmiastowe otwarcie rynku
  /setup rynek zamknij             → natychmiastowe zamknięcie rynku
  /setup rynek zaplanuj_zamkniecie → zaplanuj zamknięcie (np. 20.09.2026 18:00 / 2h / 3d)
  /setup rynek zaplanuj_otwarcie   → zaplanuj otwarcie
  /setup rynek anuluj_harmonogram  → kasuje zaplanowane zmiany

Prefix komendy (pozostawione jako skróty):
  !reset       → reset bazy (w admin.py)
  !rynek       → szybki status rynku (w market.py)
"""

from __future__ import annotations
from datetime import datetime
import discord
from discord import app_commands, ui
from discord.ext import commands
import database
import utils.league_config as cfg
from utils.helpers import (
    is_federation, build_market_status_embed,
    announce_market_change, parse_schedule_datetime, format_schedule_discord
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _is_admin(user: discord.Member) -> bool:
    return (getattr(user, "guild_permissions", None)
            and user.guild_permissions.administrator) or is_federation(user)


def _build_panel_embed() -> discord.Embed:
    """Główny embed panelu /setup ze wszystkimi aktualnymi ustawieniami."""
    all_cfg = cfg.get_all_config()
    market = database.get_market_state()
    is_open = market.get("status", "OPEN").upper() != "CLOSED"
    open_at = market.get("open_at")
    close_at = market.get("close_at")

    embed = discord.Embed(
        title="⚙️  Panel Administracyjny FSS",
        color=0x1e1f22,
        timestamp=datetime.utcnow()
    )

    # ── Sekcja: Liga ──────────────────────────────────────────────────────────
    embed.add_field(name="🏆  Ogólne", value=(
        f"> **Organizacja:** `{cfg.get_str('cfg_league_name') or 'Federacja Siatkówki Stołowej (FSS)'}`\n"
        f"> **Sezon:** `{cfg.get_str('cfg_season_label') or '2026/27'}`\n"
        f"> **Max graczy w klubie:** `{cfg.max_players()}`"
    ), inline=True)

    # ── Sekcja: Kanały ────────────────────────────────────────────────────────
    embed.add_field(name="📢  Kanały", value=(
        f"> **Forum:** `{cfg.channel_forum_id() or 'nie ustawiony'}`\n"
        f"> **Komunikaty:** `{cfg.channel_komunikaty_id() or 'nie ustawiony'}`"
    ), inline=True)

    # ── Sekcja: Role ──────────────────────────────────────────────────────────
    embed.add_field(name="🎖️  Role", value=(
        f"> **Federacja:** `{cfg.role_federacja_id() or 'nie ustawiona'}`\n"
        f"> **Wzorzec gracza:** `{cfg.rola_wzorzec_id() or 'nie ustawiony'}`"
    ), inline=True)

    # ── Sekcja: Rynek ────────────────────────────────────────────────────────
    rynek_status = "🟢  **OTWARTY**" if is_open else "🔴  **ZAMKNIĘTY**"
    rynek_lines = [f"> **Status:** {rynek_status}"]
    if close_at:
        rynek_lines.append(f"> **Zamknięcie:** {format_schedule_discord(close_at)}")
    if open_at:
        rynek_lines.append(f"> **Otwarcie:** {format_schedule_discord(open_at)}")
    if not open_at and not close_at:
        rynek_lines.append("> **Harmonogram:** brak zaplanowanych zmian")
    embed.add_field(name="🔄  Rynek Transferowy", value="\n".join(rynek_lines), inline=False)

    embed.set_footer(text=f"{cfg.league_name()} | /setup <kategoria> <opcja>")
    return embed


# ─── Widok interaktywny panelu ────────────────────────────────────────────────

class SetupPanelView(ui.View):
    """Interaktywne przyciski w głównym panelu /setup."""

    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=120)
        self.guild = guild

    async def _refresh(self, interaction: discord.Interaction):
        embed = _build_panel_embed()
        is_open = database.get_market_state().get("status", "OPEN").upper() != "CLOSED"
        # Aktualizuj etykiety przycisków
        for item in self.children:
            if isinstance(item, ui.Button):
                if item.custom_id == "mkt_toggle_open":
                    item.disabled = is_open
                elif item.custom_id == "mkt_toggle_close":
                    item.disabled = not is_open
        await interaction.response.edit_message(embed=embed, view=self)

    # ── Otwórz rynek ────────────────────────────────────────────────────────
    @ui.button(label="🟢 Otwórz Rynek", style=discord.ButtonStyle.success,
               custom_id="mkt_toggle_open", row=0)
    async def btn_open(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction.user):
            return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
        database.set_market_status("OPEN", scheduled_open="")
        await announce_market_change(
            interaction.client,
            "🔓 **RYNEK TRANSFEROWY ZOSTAŁ OTWARTY!**\n"
            "> Zarząd Federacji otworzył okienko transferowe!\n"
            "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało odblokowane.",
            guild=self.guild
        )
        await self._refresh(interaction)

    # ── Zamknij rynek ───────────────────────────────────────────────────────
    @ui.button(label="🔴 Zamknij Rynek", style=discord.ButtonStyle.danger,
               custom_id="mkt_toggle_close", row=0)
    async def btn_close(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction.user):
            return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
        database.set_market_status("CLOSED", scheduled_close="")
        await announce_market_change(
            interaction.client,
            "🔒 **RYNEK TRANSFEROWY ZOSTAŁ ZAMKNIĘTY!**\n"
            "> Zarząd Federacji zamknął okienko transferowe.\n"
            "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało zablokowane.",
            guild=self.guild
        )
        await self._refresh(interaction)

    # ── Anuluj harmonogram ──────────────────────────────────────────────────
    @ui.button(label="🗑️ Anuluj Harmonogram", style=discord.ButtonStyle.secondary,
               custom_id="mkt_cancel_schedule", row=0)
    async def btn_cancel_schedule(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction.user):
            return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
        curr = database.get_market_state()
        database.set_market_status(curr.get("status", "OPEN"), scheduled_open="", scheduled_close="")
        await self._refresh(interaction)

    # ── Odśwież panel ──────────────────────────────────────────────────────
    @ui.button(label="🔄 Odśwież", style=discord.ButtonStyle.secondary,
               custom_id="mkt_refresh", row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: ui.Button):
        await self._refresh(interaction)


# ─── Cog ─────────────────────────────────────────────────────────────────────

class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._build_tree()

    def _build_tree(self):
        # Korzeń
        setup = app_commands.Group(
            name="setup",
            description="Panel administracyjny ligi"
        )

        # Subgrupy
        liga   = app_commands.Group(name="liga",  description="Ustawienia ogólne ligi",        parent=setup)
        kanal  = app_commands.Group(name="kanal", description="ID kanałów Discord",             parent=setup)
        rola   = app_commands.Group(name="rola",  description="ID ról Discord",                 parent=setup)
        rynek  = app_commands.Group(name="rynek", description="Zarządzanie rynkiem transferowym", parent=setup)

        # ── /setup panel (bez subkomendy) → panel z UI ──────────────────────────
        @setup.command(name="panel", description="Otwórz interaktywny panel administracyjny ligi")
        async def slash_setup_panel(interaction: discord.Interaction):
            if not _is_admin(interaction.user):
                return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            embed = _build_panel_embed()
            view = SetupPanelView(interaction.guild)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # ── /setup liga ───────────────────────────────────────────────────

        @liga.command(name="max_graczy", description="Zmień maksymalną liczbę graczy w klubie")
        @app_commands.describe(liczba="Liczba od 1 do 25")
        async def slash_liga_max(interaction: discord.Interaction, liczba: int):
            if not _is_admin(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            if not 1 <= liczba <= 25:
                return await interaction.response.send_message("❌ Wartość musi być od **1** do **25**.", ephemeral=True)
            cfg.set_config("cfg_max_players", str(liczba))
            await interaction.response.send_message(
                embed=_ok(f"Max graczy w klubie zmienione na **{liczba}**.\nLimit będzie widoczny w panelu po ponownym wysłaniu `/setup_panel`."),
                ephemeral=True
            )

        @liga.command(name="sezon", description="Zmień oznaczenie aktualnego sezonu (np. 2026/27)")
        @app_commands.describe(label="Krótkie oznaczenie, np. 2026/27")
        async def slash_liga_sezon(interaction: discord.Interaction, label: str):
            if not _is_admin(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            if len(label) > 20: return await interaction.response.send_message("❌ Za długie (max 20 znaków).", ephemeral=True)
            cfg.set_config("cfg_season_label", label)
            await interaction.response.send_message(embed=_ok(f"Sezon ustawiony na **{label}**."), ephemeral=True)

        @liga.command(name="nazwa", description="Zmień nazwę organizacji (widoczna w stopkach embedów)")
        @app_commands.describe(nazwa="Pełna nazwa, np. Federacja Siatkówki Stołowej (FSS)")
        async def slash_liga_nazwa(interaction: discord.Interaction, nazwa: str):
            if not _is_admin(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            if len(nazwa) > 50: return await interaction.response.send_message("❌ Za długa (max 50 znaków).", ephemeral=True)
            cfg.set_config("cfg_league_name", nazwa)
            await interaction.response.send_message(embed=_ok(f"Nazwa organizacji zmieniona na **{nazwa}**."), ephemeral=True)


        # ── /setup kanal ──────────────────────────────────────────────────

        @kanal.command(name="forum", description="Ustaw ID kanału forum (gdzie trafiają wnioski transferowe)")
        @app_commands.describe(id_kanalu="ID kanału Discord (PPM → Kopiuj ID)")
        async def slash_kanal_forum(interaction: discord.Interaction, id_kanalu: str):
            if not _is_admin(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            try:
                cid = int(id_kanalu)
                ch = interaction.guild.get_channel(cid)
                if not ch: return await interaction.response.send_message(f"❌ Kanał `{cid}` nie istnieje na serwerze.", ephemeral=True)
                cfg.set_config("cfg_channel_forum", str(cid))
                await interaction.response.send_message(embed=_ok(f"Kanał forum: {ch.mention}"), ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Wpisz samo ID (same cyfry).", ephemeral=True)

        @kanal.command(name="komunikaty", description="Ustaw ID kanału oficjalnych komunikatów ligi")
        @app_commands.describe(id_kanalu="ID kanału Discord")
        async def slash_kanal_komunikaty(interaction: discord.Interaction, id_kanalu: str):
            if not _is_admin(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            try:
                cid = int(id_kanalu)
                ch = interaction.guild.get_channel(cid)
                if not ch: return await interaction.response.send_message(f"❌ Kanał `{cid}` nie istnieje na serwerze.", ephemeral=True)
                cfg.set_config("cfg_channel_komunikaty", str(cid))
                await interaction.response.send_message(embed=_ok(f"Kanał komunikatów: {ch.mention}"), ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Wpisz samo ID (same cyfry).", ephemeral=True)

        # ── /setup rola ───────────────────────────────────────────────────

        @rola.command(name="federacja", description="Ustaw ID roli Zarządu Federacji")
        @app_commands.describe(id_roli="ID roli Discord")
        async def slash_rola_fed(interaction: discord.Interaction, id_roli: str):
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("❌ Tylko Administrator serwera.", ephemeral=True)
            try:
                rid = int(id_roli)
                role = interaction.guild.get_role(rid)
                if not role: return await interaction.response.send_message(f"❌ Rola `{rid}` nie istnieje.", ephemeral=True)
                cfg.set_config("cfg_role_federacja", str(rid))
                await interaction.response.send_message(embed=_ok(f"Rola Federacji: {role.mention}"), ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Wpisz samo ID.", ephemeral=True)

        @rola.command(name="wzorzec", description="Ustaw ID wzorcowej roli gracza (kopiowana przy rejestracji)")
        @app_commands.describe(id_roli="ID roli Discord")
        async def slash_rola_wzorzec(interaction: discord.Interaction, id_roli: str):
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("❌ Tylko Administrator serwera.", ephemeral=True)
            try:
                rid = int(id_roli)
                role = interaction.guild.get_role(rid)
                if not role: return await interaction.response.send_message(f"❌ Rola `{rid}` nie istnieje.", ephemeral=True)
                cfg.set_config("cfg_rola_wzorzec", str(rid))
                await interaction.response.send_message(embed=_ok(f"Wzorzec roli gracza: {role.mention}"), ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Wpisz samo ID.", ephemeral=True)

        # ── /setup rynek ──────────────────────────────────────────────────

        @rynek.command(name="otworz", description="Natychmiastowe otwarcie rynku transferowego")
        async def slash_rynek_otw(interaction: discord.Interaction):
            if not _is_admin(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            database.set_market_status("OPEN", scheduled_open="")
            await announce_market_change(
                interaction.client,
                "🔓 **RYNEK TRANSFEROWY ZOSTAŁ OTWARTY!**\n"
                "> Zarząd Federacji otworzył okienko transferowe!\n"
                "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało odblokowane.",
                guild=interaction.guild
            )
            await interaction.response.send_message(embed=_ok("Rynek **otwarty**. Komunikat wysłany."), ephemeral=True)

        @rynek.command(name="zamknij", description="Natychmiastowe zamknięcie rynku transferowego")
        async def slash_rynek_zam(interaction: discord.Interaction):
            if not _is_admin(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            database.set_market_status("CLOSED", scheduled_close="")
            await announce_market_change(
                interaction.client,
                "🔒 **RYNEK TRANSFEROWY ZOSTAŁ ZAMKNIĘTY!**\n"
                "> Zarząd Federacji zamknął okienko transferowe.\n"
                "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało zablokowane.",
                guild=interaction.guild
            )
            await interaction.response.send_message(embed=_ok("Rynek **zamknięty**. Komunikat wysłany."), ephemeral=True)

        @rynek.command(name="zaplanuj_zamkniecie", description="Zaplanuj automatyczne zamknięcie rynku")
        @app_commands.describe(termin="Np. 20.09.2026 18:00 | 2h | 3d")
        async def slash_rynek_plan_close(interaction: discord.Interaction, termin: str):
            if not _is_admin(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            dt_str = parse_schedule_datetime(termin)
            if not dt_str: return await interaction.response.send_message("❌ Nieprawidłowy format. Przykład: `20.09.2026 18:00` lub `2h`, `3d`.", ephemeral=True)
            curr = database.get_market_state()
            database.set_market_status(curr.get("status", "OPEN"), scheduled_close=dt_str)
            await announce_market_change(
                interaction.client,
                f"⏰ **ZAPLANOWANO ZAMKNIĘCIE OKIENKA TRANSFEROWEGO!**\n> Zamknięcie nastąpi: {format_schedule_discord(dt_str)}",
                guild=interaction.guild
            )
            await interaction.response.send_message(
                embed=_ok(f"Zaplanowano zamknięcie: {format_schedule_discord(dt_str)}"), ephemeral=True)

        @rynek.command(name="zaplanuj_otwarcie", description="Zaplanuj automatyczne otwarcie rynku")
        @app_commands.describe(termin="Np. 20.09.2026 18:00 | 2h | 3d")
        async def slash_rynek_plan_open(interaction: discord.Interaction, termin: str):
            if not _is_admin(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            dt_str = parse_schedule_datetime(termin)
            if not dt_str: return await interaction.response.send_message("❌ Nieprawidłowy format. Przykład: `20.09.2026 18:00` lub `2h`, `3d`.", ephemeral=True)
            curr = database.get_market_state()
            database.set_market_status(curr.get("status", "OPEN"), scheduled_open=dt_str)
            await announce_market_change(
                interaction.client,
                f"🔓 **ZAPLANOWANO OTWARCIE OKIENKA TRANSFEROWEGO!**\n> Otwarcie nastąpi: {format_schedule_discord(dt_str)}",
                guild=interaction.guild
            )
            await interaction.response.send_message(
                embed=_ok(f"Zaplanowano otwarcie: {format_schedule_discord(dt_str)}"), ephemeral=True)

        @rynek.command(name="anuluj_harmonogram", description="Anuluj zaplanowane automatyczne zmiany statusu rynku")
        async def slash_rynek_cancel(interaction: discord.Interaction):
            if not _is_admin(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            curr = database.get_market_state()
            database.set_market_status(curr.get("status", "OPEN"), scheduled_open="", scheduled_close="")
            await interaction.response.send_message(embed=_ok("Harmonogram rynku wyczyszczony."), ephemeral=True)

        self._setup_group = setup

    async def cog_load(self):
        self.bot.tree.add_command(self._setup_group)

    async def cog_unload(self):
        self.bot.tree.remove_command("setup")


def _ok(text: str) -> discord.Embed:
    return discord.Embed(description=f"✅  {text}", color=0x2ecc71)


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
