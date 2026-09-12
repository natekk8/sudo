import discord
from discord import app_commands
from discord.ext import commands
import database
from utils.helpers import (is_federation, parse_schedule_datetime, format_schedule_discord, 
                           build_market_status_embed, announce_market_change)

class MarketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._setup_slash_group()

    def _setup_slash_group(self):
        self.rynek_slash_group = app_commands.Group(name='rynek', description='Zarządzanie rynkiem transferowym ligi')
        
        @self.rynek_slash_group.command(name="status", description="Sprawdź stan i harmonogram rynku transferowego")
        async def slash_rynek_status(interaction: discord.Interaction):
            embed = build_market_status_embed()
            await interaction.response.send_message(embed=embed)

        @self.rynek_slash_group.command(name="otworz", description="Otwórz rynek transferowy (odblokowuje transfery, kontrakty i wypożyczenia)")
        async def slash_rynek_otworz(interaction: discord.Interaction):
            if not (interaction.user.guild_permissions.administrator or is_federation(interaction.user)):
                return await interaction.response.send_message("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.", ephemeral=True)
            database.set_market_status("OPEN", scheduled_open="")
            await announce_market_change(
                interaction.client,
                "🔓 **RYNEK TRANSFEROWY ZOSTAŁ OTWARTY!**\n"
                "> Zarząd Federacji otworzył okienko transferowe!\n"
                "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało odblokowane.",
                guild=interaction.guild
            )
            await interaction.response.send_message("✅ Rynek transferowy został otwarty!", ephemeral=True)

        @self.rynek_slash_group.command(name="zamknij", description="Zamknij rynek transferowy (blokuje transfery, kontrakty i wypożyczenia)")
        async def slash_rynek_zamknij(interaction: discord.Interaction):
            if not (interaction.user.guild_permissions.administrator or is_federation(interaction.user)):
                return await interaction.response.send_message("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.", ephemeral=True)
            database.set_market_status("CLOSED", scheduled_close="")
            await announce_market_change(
                interaction.client,
                "🔒 **RYNEK TRANSFEROWY ZOSTAŁ ZAMKNIĘTY!**\n"
                "> Zarząd Federacji zamknął okienko transferowe.\n"
                "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało zablokowane.",
                guild=interaction.guild
            )
            await interaction.response.send_message("✅ Rynek transferowy został zamknięty!", ephemeral=True)

        @self.rynek_slash_group.command(name="zaplanuj_zamkniecie", description="Zaplanuj automatyczne zamknięcie rynku transferowego")
        @app_commands.describe(termin="Data i godzina (np. 20.09.2026 18:00 lub 2h, 3d)")
        async def slash_rynek_plan_close(interaction: discord.Interaction, termin: str):
            if not (interaction.user.guild_permissions.administrator or is_federation(interaction.user)):
                return await interaction.response.send_message("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.", ephemeral=True)
            dt_str = parse_schedule_datetime(termin)
            if not dt_str:
                return await interaction.response.send_message("❌ Nieprawidłowy format daty! Użyj np. `20.09.2026 18:00` lub `2h`, `3d`.", ephemeral=True)
            curr = database.get_market_state()
            database.set_market_status(curr.get("status", "OPEN"), scheduled_close=dt_str)
            await announce_market_change(
                interaction.client,
                f"⏰ **ZAPLANOWANO ZAMKNIĘCIE OKIENKA TRANSFEROWEGO!**\n"
                f"> Zamknięcie nastąpi: {format_schedule_discord(dt_str)}",
                guild=interaction.guild
            )
            await interaction.response.send_message(f"✅ Zaplanowano zamknięcie rynku na: `{dt_str}` ({format_schedule_discord(dt_str)}).", ephemeral=True)

        @self.rynek_slash_group.command(name="zaplanuj_otwarcie", description="Zaplanuj automatyczne otwarcie rynku transferowego")
        @app_commands.describe(termin="Data i godzina (np. 20.09.2026 18:00 lub 2h, 3d)")
        async def slash_rynek_plan_open(interaction: discord.Interaction, termin: str):
            if not (interaction.user.guild_permissions.administrator or is_federation(interaction.user)):
                return await interaction.response.send_message("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.", ephemeral=True)
            dt_str = parse_schedule_datetime(termin)
            if not dt_str:
                return await interaction.response.send_message("❌ Nieprawidłowy format daty! Użyj np. `20.09.2026 18:00` lub `2h`, `3d`.", ephemeral=True)
            curr = database.get_market_state()
            database.set_market_status(curr.get("status", "OPEN"), scheduled_open=dt_str)
            await announce_market_change(
                interaction.client,
                f"🔓 **ZAPLANOWANO OTWARCIE OKIENKA TRANSFEROWEGO!**\n"
                f"> Otwarcie nastąpi: {format_schedule_discord(dt_str)}",
                guild=interaction.guild
            )
            await interaction.response.send_message(f"✅ Zaplanowano otwarcie rynku na: `{dt_str}` ({format_schedule_discord(dt_str)}).", ephemeral=True)

        @self.rynek_slash_group.command(name="reset_bazy", description="Reset bazy danych na nowy sezon 2026/27 (Zarząd Federacji / Admin)")
        async def slash_rynek_reset_bazy(interaction: discord.Interaction):
            if not (interaction.user.guild_permissions.administrator or is_federation(interaction.user)):
                return await interaction.response.send_message("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.", ephemeral=True)
            database.reset_database_for_new_season()
            embed = discord.Embed(
                title="🏆 Nowy Sezon 2026/27 Rozpoczęty!",
                description=(
                    "Baza danych została zresetowana na nowy sezon 2026/27:\n"
                    "• Wszystkie tabele i liczniki ticketów zresetowane.\n"
                    "• Okienko transferowe ustawione w stan: **OTWARTY**."
                ),
                color=0x2ecc71
            )
            await interaction.response.send_message(embed=embed)
            
        self.bot.tree.add_command(self.rynek_slash_group)


    @commands.group(name="rynek", invoke_without_command=True)
    async def rynek_prefix_group(self, ctx):
        embed = build_market_status_embed()
        await ctx.reply(embed=embed)

    @rynek_prefix_group.command(name="status")
    async def rynek_prefix_status(self, ctx):
        embed = build_market_status_embed()
        await ctx.reply(embed=embed)

    @rynek_prefix_group.command(name="otworz")
    async def rynek_prefix_otworz(self, ctx):
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
        database.set_market_status("OPEN", scheduled_open="")
        await announce_market_change(
            self.bot,
            "🔓 **RYNEK TRANSFEROWY ZOSTAŁ OTWARTY!**\n"
            "> Zarząd Federacji otworzył okienko transferowe!\n"
            "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało odblokowane.",
            guild=ctx.guild
        )
        await ctx.reply("✅ Rynek transferowy został otwarty!")

    @rynek_prefix_group.command(name="zamknij")
    async def rynek_prefix_zamknij(self, ctx):
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
        database.set_market_status("CLOSED", scheduled_close="")
        await announce_market_change(
            self.bot,
            "🔒 **RYNEK TRANSFEROWY ZOSTAŁ ZAMKNIĘTY!**\n"
            "> Zarząd Federacji zamknął okienko transferowe.\n"
            "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało zablokowane.",
            guild=ctx.guild
        )
        await ctx.reply("✅ Rynek transferowy został zamknięty!")

    @rynek_prefix_group.command(name="zaplanuj_zamkniecie")
    async def rynek_prefix_plan_close(self, ctx, *, termin: str):
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
        dt_str = parse_schedule_datetime(termin)
        if not dt_str:
            return await ctx.reply("❌ Nieprawidłowy format daty! Użyj np. `20.09.2026 18:00` lub `2h`, `3d`.")
        curr = database.get_market_state()
        database.set_market_status(curr.get("status", "OPEN"), scheduled_close=dt_str)
        await announce_market_change(
            self.bot,
            f"⏰ **ZAPLANOWANO ZAMKNIĘCIE OKIENKA TRANSFEROWEGO!**\n"
            f"> Zamknięcie nastąpi: {format_schedule_discord(dt_str)}",
            guild=ctx.guild
        )
        await ctx.reply(f"✅ Zaplanowano zamknięcie rynku na: `{dt_str}` ({format_schedule_discord(dt_str)}).")

    @rynek_prefix_group.command(name="zaplanuj_otwarcie")
    async def rynek_prefix_plan_open(self, ctx, *, termin: str):
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
        dt_str = parse_schedule_datetime(termin)
        if not dt_str:
            return await ctx.reply("❌ Nieprawidłowy format daty! Użyj np. `20.09.2026 18:00` lub `2h`, `3d`.")
        curr = database.get_market_state()
        database.set_market_status(curr.get("status", "OPEN"), scheduled_open=dt_str)
        await announce_market_change(
            self.bot,
            f"🔓 **ZAPLANOWANO OTWARCIE OKIENKA TRANSFEROWEGO!**\n"
            f"> Otwarcie nastąpi: {format_schedule_discord(dt_str)}",
            guild=ctx.guild
        )
        await ctx.reply(f"✅ Zaplanowano otwarcie rynku na: `{dt_str}` ({format_schedule_discord(dt_str)}).")

    @rynek_prefix_group.command(name="reset_bazy")
    async def rynek_prefix_reset_bazy(self, ctx):
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
        database.reset_database_for_new_season()
        embed = discord.Embed(
            title="🏆 Nowy Sezon 2026/27 Rozpoczęty!",
            description=(
                "Baza danych została zresetowana na nowy sezon 2026/27:\n"
                "• Wszystkie tabele i liczniki ticketów zresetowane.\n"
                "• Okienko transferowe ustawione w stan: **OTWARTY**."
            ),
            color=0x2ecc71
        )
        await ctx.reply(embed=embed)


async def setup(bot):
    await bot.add_cog(MarketCog(bot))
