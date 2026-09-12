"""
cogs/market.py
==============
Minimalny cog rynku: tylko prefix !rynek (skrot do szybkiego sprawdzenia statusu).
Cala logika slash commands (/setup rynek ...) jest w cogs/setup_cog.py.
"""
import discord
from discord.ext import commands
import database
from utils.helpers import is_federation, build_market_status_embed


class MarketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='rynek')
    async def cmd_rynek(self, ctx):
        """Skrot do sprawdzenia statusu rynku transferowego."""
        embed = build_market_status_embed()
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MarketCog(bot))
