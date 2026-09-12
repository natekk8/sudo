import os, tempfile
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
import database
from utils.helpers import is_federation

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='backup_db')
    async def backup_db(self, ctx):
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")

        temp_fd, temp_path = tempfile.mkstemp(suffix=".db", prefix="liga_backup_")
        os.close(temp_fd)
        os.remove(temp_path)

        try:
            database.backup_database_vacuum(temp_path)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"liga_backup_{timestamp}.db"
            await ctx.reply(
                f"📦 **Kopia zapasowa bazy danych** (`{filename}`):\n"
                f"> Tryb: WAL-safe atomic vacuum snapshot",
                file=discord.File(temp_path, filename=filename)
            )
        except Exception as e:
            await ctx.reply(f"❌ Błąd tworzenia kopii zapasowej: `{e}`")
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    @commands.command(name='db_stats')
    async def db_stats(self, ctx):
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień.")

        stats = database.get_db_file_stats()
        embed = discord.Embed(title="🗄️ Statystyki bazy SQLite", color=0x2b2d31)
        embed.add_field(name="Rozmiar pliku", value=f"`{stats.get('file_size_kb', 0)} KB`", inline=True)
        embed.add_field(name="Tryb Journal", value=f"`{stats.get('journal_mode', '?')}`", inline=True)
        embed.add_field(name="Klucze obce", value=f"`{stats.get('foreign_keys', '?')}`", inline=True)

        counts = (
            f"• Kluby: `{stats.get('clubs', 0)}`\n"
            f"• Zawodnicy: `{stats.get('players', 0)}`\n"
            f"• Wolni Agenci: `{stats.get('free_agents', 0)}`\n"
            f"• Wnioski: `{stats.get('applications', 0)}`\n"
            f"• Historia transferów: `{stats.get('transfer_history', 0)}`"
        )
        embed.add_field(name="Liczba rekordów", value=counts, inline=False)
        await ctx.reply(embed=embed)

    @commands.command(name='reset_sezon', aliases=['reset_bazy', 'reset_ligi', 'reset'])
    async def reset_sezon(self, ctx):
        if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
            return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")

        database.reset_database_for_new_season()
        embed = discord.Embed(
            title="🏆 Liga Zresetowana — Sezon 2026/27",
            description="Baza danych wyczyszczona z powodzeniem.",
            color=0x2ecc71
        )
        embed.add_field(name="📋 Co zresetowano", value=(
            "> • Tabele: **clubs**, **players**, **applications**\n"
            "> • Tabele: **transfer_history**, **free_agents**\n"
            "> • Licznik ticketów → `#001`\n"
            "> • Rynek transferowy → **OTWARTY**"
        ), inline=False)
        embed.add_field(name="✅ Status", value="Baza gotowa na nowy sezon.", inline=False)
        embed.set_footer(text=f"Liga Federacji • {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        await ctx.reply(embed=embed)

    @app_commands.command(name='reset', description='Zresetuj ligę na nowy sezon 2026/27')
    async def slash_reset(self, interaction: discord.Interaction):
        await self.slash_reset_sezon(interaction)

    @app_commands.command(name='reset_sezon', description='Zresetuj bazę danych i liczniki ligi na nowy sezon 2026/27')
    async def slash_reset_sezon(self, interaction: discord.Interaction):
        if not (interaction.user.guild_permissions.administrator or is_federation(interaction.user)):
            return await interaction.response.send_message("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.", ephemeral=True)

        database.reset_database_for_new_season()
        embed = discord.Embed(
            title="🏆 Liga Zresetowana — Sezon 2026/27",
            description="Baza danych wyczyszczona z powodzeniem.",
            color=0x2ecc71
        )
        embed.add_field(name="📋 Co zresetowano", value=(
            "> • Tabele: **clubs**, **players**, **applications**\n"
            "> • Tabele: **transfer_history**, **free_agents**\n"
            "> • Licznik ticketów → `#001`\n"
            "> • Rynek transferowy → **OTWARTY**"
        ), inline=False)
        embed.add_field(name="✅ Status", value="Baza gotowa na nowy sezon.", inline=False)
        embed.set_footer(text=f"Liga Federacji • {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
