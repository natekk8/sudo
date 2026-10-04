"""
cogs/market.py
==============
Komendy rynku i klubów ligi:
- /klub info <tag>  -> Karta klubu: skład, zapełnienie kadry, lista transferowa, władze
- /klub lista       -> Lista wszystkich zarejestrowanych klubów i ich kadr
- !rynek            -> Skrót do szybkiego sprawdzenia statusu rynku
- !klub <tag>       -> Szybkie sprawdzenie karty klubu
"""
from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands
import database
import utils.league_config as league_config
from utils.helpers import (
    is_federation, build_market_status_embed, build_squad_bar,
    format_price, format_expiry_discord
)


def _build_club_info_embed(club_tag: str) -> discord.Embed | None:
    tag = (club_tag or "").strip().upper()
    club = database.get_club(tag)
    if not club:
        return None

    name = club.get("name") or tag
    rep_id = club.get("reprezentant_dc")
    board_ids = club.get("board_ids") or []
    r_board = club.get("role_board_id")
    r_player = club.get("role_player_id")

    players = database.get_club_players(tag)
    max_c = league_config.max_players()
    squad_bar = build_squad_bar(len(players), max_c)

    embed = discord.Embed(
        title=f"🏛️ {name} [{tag}]",
        description=f"> Oficjalna karta klubu w Federacji Siatkówki Stołowej (FSS).\n> Kadra: {squad_bar}",
        color=0x2b5278
    )

    # ── Władze klubu ──
    board_mentions = []
    if rep_id:
        board_mentions.append(f"• Reprezentant: <@{rep_id}>")
    for bid in board_ids:
        if bid != rep_id:
            board_mentions.append(f"• Zarząd: <@{bid}>")
    if not board_mentions:
        board_mentions.append("*Brak przypisanych osób z ID Discord.*")

    role_info = []
    if r_board: role_info.append(f"<@&{r_board}>")
    if r_player: role_info.append(f"<@&{r_player}>")
    roles_str = " • ".join(role_info) if role_info else "*Brak ról*"

    embed.add_field(
        name="👔 Władze i Role Klubu",
        value="\n".join(board_mentions) + f"\n> Role: {roles_str}",
        inline=False
    )

    # ── Skład drużyny ──
    if players:
        p_lines = []
        for p in players:
            p_name = p.get("name", "Zawodnik")
            p_dc = p.get("discord_id")
            p_mention = f"<@{p_dc}>" if p_dc else f"**{p_name}**"
            clause = format_price(p.get("clause"))
            ctype = p.get("contract_type", "TRANSFER")
            wygasa = format_expiry_discord(p.get("expires_at"))

            extra = ""
            if ctype == "WYPOZYCZENIE":
                parent = p.get("parent_club_tag") or "Macierzysty"
                extra = f" *(Wypożyczony z `{parent}`)*"
            if p.get("is_overflow") == 1:
                extra += " ⚠️ **[OVERFLOW - 4. ZAWODNIK]**"

            p_lines.append(f"• {p_mention}{extra}\n  └ Klauzula: `{clause}` • Wygasa: {wygasa}")
        embed.add_field(name=f"👥 Kadra Zespołu ({len(players)}/{max_c})", value="\n".join(p_lines), inline=False)
    else:
        embed.add_field(name="👥 Kadra Zespołu", value="*Brak zarejestrowanych zawodników w kadrze.*", inline=False)

    # ── Lista transferowa ──
    all_tlist = database.get_transfer_list()
    club_tlist = [t for t in all_tlist if (t.get("club_tag") or "").upper() == tag]
    if club_tlist:
        t_lines = []
        for t in club_tlist:
            t_name = t.get("player_name", "Zawodnik")
            t_dc = t.get("discord_id")
            t_ment = f"<@{t_dc}>" if t_dc else f"**{t_name}**"
            price = format_price(t.get("price"))
            t_lines.append(f"• {t_ment} — **{price}**")
        embed.add_field(name="🏷️ Wystawieni na Listę Transferową", value="\n".join(t_lines), inline=False)

    embed.set_footer(text=f"{league_config.league_name()} • Sezon {league_config.season_label()}")
    return embed


def _build_all_clubs_embed() -> discord.Embed:
    clubs = database.get_all_clubs()
    max_c = league_config.max_players()
    counts = database.get_club_player_counts()

    embed = discord.Embed(
        title="🏛️ Kluby Federacji Siatkówki Stołowej (FSS)",
        description=f"> Zarejestrowane kluby w sezonie **{league_config.season_label()}**.\n> Użyj `/klub info <tag>`, aby zobaczyć szczegóły danego zespołu.",
        color=0x2ecc71
    )

    if not clubs:
        embed.add_field(name="Kluby", value="*Brak zarejestrowanych klubów w bazie danych.*")
        return embed

    lines = []
    for c in sorted(clubs, key=lambda x: x.get("tag", "")):
        tag = c.get("tag", "").upper()
        name = c.get("name", tag)
        cnt = counts.get(tag, 0)
        squad_bar = build_squad_bar(cnt, max_c)
        lines.append(f"**`[{tag}]` {name}**\n└ {squad_bar}")

    embed.add_field(name=f"Zarejestrowane Zespoły ({len(clubs)})", value="\n\n".join(lines)[:4000], inline=False)
    embed.set_footer(text=f"{league_config.league_name()}")
    return embed


class MarketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._register_slash_commands()

    def _register_slash_commands(self):
        klub_group = app_commands.Group(name="klub", description="Informacje o klubach i kadrach w lidze")

        async def club_tag_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
            clubs = database.get_all_clubs()
            choices = []
            for c in clubs:
                tag = c.get("tag", "").upper()
                name = c.get("name", "")
                if current.upper() in tag or current.lower() in name.lower():
                    choices.append(app_commands.Choice(name=f"[{tag}] {name}"[:100], value=tag))
            return choices[:25]

        @klub_group.command(name="info", description="Karta klubu: skład, pojemność kadry, lista transferowa i zarząd")
        @app_commands.describe(tag="Skrót (tag) klubu, np. LEG, WIS")
        @app_commands.autocomplete(tag=club_tag_autocomplete)
        async def slash_klub_info(interaction: discord.Interaction, tag: str):
            embed = _build_club_info_embed(tag)
            if not embed:
                all_tags = ", ".join([f"`{c['tag']}`" for c in database.get_all_clubs()]) or "brak"
                return await interaction.response.send_message(
                    f"❌ Nie znaleziono klubu o tagu `{tag.upper()}`.\n> Dostępne kluby: {all_tags}",
                    ephemeral=True
                )
            await interaction.response.send_message(embed=embed)

        @klub_group.command(name="lista", description="Lista wszystkich klubów ligi z podsumowaniem kadr")
        async def slash_klub_lista(interaction: discord.Interaction):
            embed = _build_all_clubs_embed()
            await interaction.response.send_message(embed=embed)

        self.klub_group = klub_group

    async def cog_load(self):
        self.bot.tree.add_command(self.klub_group)

    async def cog_unload(self):
        self.bot.tree.remove_command("klub")

    @commands.command(name='rynek')
    async def cmd_rynek(self, ctx):
        """Skrót do sprawdzenia statusu rynku transferowego."""
        embed = build_market_status_embed()
        await ctx.reply(embed=embed)

    @commands.command(name='klub', aliases=['klub_info', 'druzyna'])
    async def cmd_klub(self, ctx, tag: str = None):
        """
        Pokazuje kartę klubu:
        !klub LEG -> Wyświetla kadrę, wolne miejsca i zarząd Legii
        !klub     -> Wyświetla listę wszystkich klubów
        """
        if not tag:
            embed = _build_all_clubs_embed()
            return await ctx.reply(embed=embed)

        embed = _build_club_info_embed(tag)
        if not embed:
            all_tags = ", ".join([f"`{c['tag']}`" for c in database.get_all_clubs()]) or "brak"
            return await ctx.reply(f"❌ Nie znaleziono klubu o tagu `{tag.upper()}`.\n> Dostępne kluby: {all_tags}")
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MarketCog(bot))
