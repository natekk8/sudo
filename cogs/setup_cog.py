"""
cogs/setup_cog.py
=================
Komenda /setup dla administratorow i Zarzadu Federacji.
Pozwala dynamicznie zmieniac wszystkie ustawienia ligi bez restartu bota:
  - Max graczy w klubie
  - ID kanalow (forum, komunikaty)
  - ID rol (Federacja, wzorzec gracza)
  - Rynek transferowy (otworz, zamknij, zaplanuj)
  - Oznaczenie sezonu i nazwe ligi
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import database
from utils.helpers import is_federation, parse_schedule_datetime, format_schedule_discord, announce_market_change
import utils.league_config as cfg

_BOOL_TRUE = {"tak", "true", "1", "open", "otwarty"}
_BOOL_FALSE = {"nie", "false", "0", "closed", "zamkniety"}


def _is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator or is_federation(interaction.user)


def _build_status_embed() -> discord.Embed:
    """Embed ze wszystkimi aktualnymi ustawieniami ligi."""
    all_cfg = cfg.get_all_config()
    market = database.get_market_state()
    market_status = market.get("status", "OPEN")
    market_icon = "OPEN" if market_status.upper() != "CLOSED" else "CLOSED"

    embed = discord.Embed(
        title="⚙️ Panel Konfiguracji Ligi",
        description=(
            "Aktualne ustawienia ligi. Zmien dowolne przez `/setup <opcja> <wartosc>`.\n"
            "> Zmiany sa natychmiastowe i nie wymagaja restartu bota."
        ),
        color=0x2b2d31,
        timestamp=datetime.utcnow()
    )

    # Ustawienia ogolne
    general = "\n".join(
        f"> **{v['label']}**: `{v['value'] or v['default']}`"
        for k, v in all_cfg.items()
        if k in ("cfg_max_players", "cfg_season_label", "cfg_league_name")
    )
    embed.add_field(name="🏆 Ogolne", value=general, inline=False)

    # ID kanalow
    channels = "\n".join(
        f"> **{v['label']}**: `{v['value'] or v['default']}`"
        for k, v in all_cfg.items()
        if k in ("cfg_channel_forum", "cfg_channel_komunikaty")
    )
    embed.add_field(name="📢 Kanaly", value=channels, inline=False)

    # ID rol
    roles = "\n".join(
        f"> **{v['label']}**: `{v['value'] or v['default']}`"
        for k, v in all_cfg.items()
        if k in ("cfg_role_federacja", "cfg_rola_wzorzec")
    )
    embed.add_field(name="🎖️ Role", value=roles, inline=False)

    # Rynek transferowy
    is_open = market_status.upper() != "CLOSED"
    open_at = market.get("open_at")
    close_at = market.get("close_at")
    rynek_lines = [
        f"> **Status**: {'🟢 OTWARTY' if is_open else '🔴 ZAMKNIETY'}"
    ]
    if close_at:
        rynek_lines.append(f"> **Zaplanowane zamkniecie**: {format_schedule_discord(close_at)}")
    if open_at:
        rynek_lines.append(f"> **Zaplanowane otwarcie**: {format_schedule_discord(open_at)}")
    if not open_at and not close_at:
        rynek_lines.append("> **Harmonogram**: Brak zaplanowanych zmian")
    embed.add_field(name="🔄 Rynek Transferowy", value="\n".join(rynek_lines), inline=False)

    embed.set_footer(text="Liga Federacji | /setup <opcja> <wartosc> aby zmienic")
    return embed


class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._setup_slash_group()

    def _setup_slash_group(self):
        setup = app_commands.Group(
            name="setup",
            description="Konfiguracja ligi dla administratorow i Zarzadu Federacji"
        )

        # ── /setup status ─────────────────────────────────────────────────────
        @setup.command(name="status", description="Pokaz wszystkie aktualne ustawienia ligi")
        async def slash_setup_status(interaction: discord.Interaction):
            if not _is_admin(interaction):
                return await interaction.response.send_message("❌ Brak uprawnien.", ephemeral=True)
            embed = _build_status_embed()
            await interaction.response.send_message(embed=embed, ephemeral=True)

        # ── /setup max_graczy ──────────────────────────────────────────────────
        @setup.command(name="max_graczy", description="Ustaw maksymalna liczbe graczy w klubie (np. 3)")
        @app_commands.describe(liczba="Maksymalna liczba graczy na klub (min. 1, max. 25)")
        async def slash_setup_max(interaction: discord.Interaction, liczba: int):
            if not _is_admin(interaction):
                return await interaction.response.send_message("❌ Brak uprawnien.", ephemeral=True)
            if not (1 <= liczba <= 25):
                return await interaction.response.send_message(
                    "❌ Liczba musi byc miedzy **1** a **25**.", ephemeral=True)
            cfg.set_config("cfg_max_players", str(liczba))
            embed = discord.Embed(
                title="✅ Ustawienie zaktualizowane",
                description=f"Maksymalna liczba graczy w klubie zmieniona na: **{liczba}**\n"
                            f"> Wiadomosci panelu beda dynamicznie pokazywac nowy limit.",
                color=0x2ecc71
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        # ── /setup kanal_forum ─────────────────────────────────────────────────
        @setup.command(name="kanal_forum", description="Ustaw ID kanalu forum (gdzie trafiaja wnioski)")
        @app_commands.describe(id_kanalu="ID kanalu Discord (skopiuj: PPM na kanal -> Kopiuj ID)")
        async def slash_setup_forum(interaction: discord.Interaction, id_kanalu: str):
            if not _is_admin(interaction):
                return await interaction.response.send_message("❌ Brak uprawnien.", ephemeral=True)
            try:
                chan_id = int(id_kanalu)
                ch = interaction.guild.get_channel(chan_id)
                if ch is None:
                    return await interaction.response.send_message(
                        f"❌ Kanal o ID `{chan_id}` nie istnieje na tym serwerze.", ephemeral=True)
                cfg.set_config("cfg_channel_forum", str(chan_id))
                embed = discord.Embed(
                    title="✅ Kanal forum zaktualizowany",
                    description=f"Wnioski beda trafialy do: {ch.mention} (`{chan_id}`)",
                    color=0x2ecc71
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Nieprawidlowe ID — podaj same cyfry.", ephemeral=True)

        # ── /setup kanal_komunikaty ────────────────────────────────────────────
        @setup.command(name="kanal_komunikaty", description="Ustaw ID kanalu komunikatow ligi")
        @app_commands.describe(id_kanalu="ID kanalu Discord")
        async def slash_setup_komunikaty(interaction: discord.Interaction, id_kanalu: str):
            if not _is_admin(interaction):
                return await interaction.response.send_message("❌ Brak uprawnien.", ephemeral=True)
            try:
                chan_id = int(id_kanalu)
                ch = interaction.guild.get_channel(chan_id)
                if ch is None:
                    return await interaction.response.send_message(
                        f"❌ Kanal o ID `{chan_id}` nie istnieje na tym serwerze.", ephemeral=True)
                cfg.set_config("cfg_channel_komunikaty", str(chan_id))
                embed = discord.Embed(
                    title="✅ Kanal komunikatow zaktualizowany",
                    description=f"Komunikaty liga beda trafialy do: {ch.mention} (`{chan_id}`)",
                    color=0x2ecc71
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Nieprawidlowe ID.", ephemeral=True)

        # ── /setup rola_federacja ──────────────────────────────────────────────
        @setup.command(name="rola_federacja", description="Ustaw ID roli Zarzadu Federacji")
        @app_commands.describe(id_roli="ID roli Discord")
        async def slash_setup_fed(interaction: discord.Interaction, id_roli: str):
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message(
                    "❌ Tylko Administrator serwera moze zmienic role.", ephemeral=True)
            try:
                role_id = int(id_roli)
                role = interaction.guild.get_role(role_id)
                if role is None:
                    return await interaction.response.send_message(
                        f"❌ Rola o ID `{role_id}` nie istnieje.", ephemeral=True)
                cfg.set_config("cfg_role_federacja", str(role_id))
                embed = discord.Embed(
                    title="✅ Rola Federacji zaktualizowana",
                    description=f"Rola Zarzadu Federacji ustawiona na: {role.mention} (`{role_id}`)",
                    color=0x2ecc71
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Nieprawidlowe ID.", ephemeral=True)

        # ── /setup rola_wzorzec ────────────────────────────────────────────────
        @setup.command(name="rola_wzorzec", description="Ustaw ID wzorcowej roli gracza")
        @app_commands.describe(id_roli="ID roli Discord")
        async def slash_setup_wzorzec(interaction: discord.Interaction, id_roli: str):
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message(
                    "❌ Tylko Administrator serwera moze zmienic role.", ephemeral=True)
            try:
                role_id = int(id_roli)
                role = interaction.guild.get_role(role_id)
                if role is None:
                    return await interaction.response.send_message(
                        f"❌ Rola o ID `{role_id}` nie istnieje.", ephemeral=True)
                cfg.set_config("cfg_rola_wzorzec", str(role_id))
                embed = discord.Embed(
                    title="✅ Wzorzec roli gracza zaktualizowany",
                    description=f"Wzorzec roli gracza ustawiony na: {role.mention} (`{role_id}`)",
                    color=0x2ecc71
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Nieprawidlowe ID.", ephemeral=True)

        # ── /setup sezon ───────────────────────────────────────────────────────
        @setup.command(name="sezon", description="Ustaw oznaczenie sezonu (np. 2026/27)")
        @app_commands.describe(label="Oznaczenie sezonu, np. 2026/27")
        async def slash_setup_sezon(interaction: discord.Interaction, label: str):
            if not _is_admin(interaction):
                return await interaction.response.send_message("❌ Brak uprawnien.", ephemeral=True)
            if len(label) > 20:
                return await interaction.response.send_message("❌ Zbyt dlugie oznaczenie (max 20 znakow).", ephemeral=True)
            cfg.set_config("cfg_season_label", label)
            await interaction.response.send_message(
                f"✅ Oznaczenie sezonu zmienione na: **{label}**", ephemeral=True)

        # ── /setup nazwa_ligi ──────────────────────────────────────────────────
        @setup.command(name="nazwa_ligi", description="Ustaw nazwe ligi (pojawia sie w footerach)")
        @app_commands.describe(nazwa="Nazwa ligi, np. Liga Federacji")
        async def slash_setup_nazwa(interaction: discord.Interaction, nazwa: str):
            if not _is_admin(interaction):
                return await interaction.response.send_message("❌ Brak uprawnien.", ephemeral=True)
            if len(nazwa) > 50:
                return await interaction.response.send_message("❌ Zbyt dluga nazwa (max 50 znakow).", ephemeral=True)
            cfg.set_config("cfg_league_name", nazwa)
            await interaction.response.send_message(
                f"✅ Nazwa ligi zmieniona na: **{nazwa}**", ephemeral=True)

        # ── /setup rynek_otworz ────────────────────────────────────────────────
        @setup.command(name="rynek_otworz", description="Natychmiastowe otwarcie rynku transferowego")
        async def slash_setup_rynek_otw(interaction: discord.Interaction):
            if not _is_admin(interaction):
                return await interaction.response.send_message("❌ Brak uprawnien.", ephemeral=True)
            database.set_market_status("OPEN", scheduled_open="")
            await announce_market_change(
                interaction.client,
                "🔓 **RYNEK TRANSFEROWY ZOSTAL OTWARTY!**\n"
                "> Zarzad Federacji otworzyl okienko transferowe!\n"
                "> Skladanie wnioskow transferowych, kontraktowych i wypozyczen zostalo odblokowane.",
                guild=interaction.guild
            )
            await interaction.response.send_message("✅ Rynek transferowy otwarty!", ephemeral=True)

        # ── /setup rynek_zamknij ───────────────────────────────────────────────
        @setup.command(name="rynek_zamknij", description="Natychmiastowe zamkniecie rynku transferowego")
        async def slash_setup_rynek_zam(interaction: discord.Interaction):
            if not _is_admin(interaction):
                return await interaction.response.send_message("❌ Brak uprawnien.", ephemeral=True)
            database.set_market_status("CLOSED", scheduled_close="")
            await announce_market_change(
                interaction.client,
                "🔒 **RYNEK TRANSFEROWY ZOSTAL ZAMKNIETY!**\n"
                "> Zarzad Federacji zamknal okienko transferowe.\n"
                "> Skladanie wnioskow transferowych, kontraktowych i wypozyczen zostalo zablokowane.",
                guild=interaction.guild
            )
            await interaction.response.send_message("✅ Rynek transferowy zamkniety!", ephemeral=True)

        # ── /setup rynek_zaplanuj_zamkniecie ──────────────────────────────────
        @setup.command(name="rynek_zaplanuj_zamkniecie", description="Zaplanuj automatyczne zamkniecie rynku")
        @app_commands.describe(termin="Data i godzina (np. 20.09.2026 18:00 lub 2h, 3d)")
        async def slash_setup_plan_close(interaction: discord.Interaction, termin: str):
            if not _is_admin(interaction):
                return await interaction.response.send_message("❌ Brak uprawnien.", ephemeral=True)
            dt_str = parse_schedule_datetime(termin)
            if not dt_str:
                return await interaction.response.send_message(
                    "❌ Nieprawidlowy format! Uzyj np. `20.09.2026 18:00` lub `2h`, `3d`.", ephemeral=True)
            curr = database.get_market_state()
            database.set_market_status(curr.get("status", "OPEN"), scheduled_close=dt_str)
            await announce_market_change(
                interaction.client,
                f"⏰ **ZAPLANOWANO ZAMKNIECIE OKIENKA TRANSFEROWEGO!**\n"
                f"> Zamkniecie nastapi: {format_schedule_discord(dt_str)}",
                guild=interaction.guild
            )
            await interaction.response.send_message(
                f"✅ Zaplanowano zamkniecie rynku: {format_schedule_discord(dt_str)}", ephemeral=True)

        # ── /setup rynek_zaplanuj_otwarcie ────────────────────────────────────
        @setup.command(name="rynek_zaplanuj_otwarcie", description="Zaplanuj automatyczne otwarcie rynku")
        @app_commands.describe(termin="Data i godzina (np. 20.09.2026 18:00 lub 2h, 3d)")
        async def slash_setup_plan_open(interaction: discord.Interaction, termin: str):
            if not _is_admin(interaction):
                return await interaction.response.send_message("❌ Brak uprawnien.", ephemeral=True)
            dt_str = parse_schedule_datetime(termin)
            if not dt_str:
                return await interaction.response.send_message(
                    "❌ Nieprawidlowy format! Uzyj np. `20.09.2026 18:00` lub `2h`, `3d`.", ephemeral=True)
            curr = database.get_market_state()
            database.set_market_status(curr.get("status", "OPEN"), scheduled_open=dt_str)
            await announce_market_change(
                interaction.client,
                f"🔓 **ZAPLANOWANO OTWARCIE OKIENKA TRANSFEROWEGO!**\n"
                f"> Otwarcie nastapi: {format_schedule_discord(dt_str)}",
                guild=interaction.guild
            )
            await interaction.response.send_message(
                f"✅ Zaplanowano otwarcie rynku: {format_schedule_discord(dt_str)}", ephemeral=True)

        self.setup_slash_group = setup

    async def cog_load(self):
        self.bot.tree.add_command(self.setup_slash_group)

    async def cog_unload(self):
        self.bot.tree.remove_command("setup")


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
