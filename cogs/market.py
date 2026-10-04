"""
cogs/market.py
==============
Komendy rynku i klubów ligi:
- /klub info <tag>    -> Karta klubu: skład, zapełnienie kadry, lista transferowa, władze
- /klub lista         -> Lista wszystkich zarejestrowanych klubów i ich kadr
- /klub zarzad <tag>  -> Zarządzanie władzami klubu (właściciel, zarząd) bez ruszania kontraktów
- !rynek              -> Skrót do szybkiego sprawdzenia statusu rynku
- !klub <tag>         -> Szybkie sprawdzenie karty klubu
- !klub_zarzad <tag>  -> Edycja lub podgląd zarządu klubu
"""
from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands
import database
from config import CHANNEL_KOMUNIKATY_ID
import utils.league_config as league_config
from utils.helpers import (
    is_federation, is_admin_or_federation, is_club_board_or_owner,
    get_or_fetch_member, extract_ids, clean_tag,
    build_market_status_embed, build_squad_bar,
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


CLEAR_KEYWORDS = {"brak", "usun", "usuń", "none", "clear", "wyczysc", "wyczyść", "-", "puste"}


async def _update_club_board_data(guild: discord.Guild | None, author: discord.Member | discord.User,
                                  tag: str, wlasciciel: str | None, zarzad: str | None) -> tuple[bool, str, discord.Embed | None]:
    c_tag = clean_tag(tag)
    club = database.get_club(c_tag)
    if not club:
        all_tags = ", ".join([f"`{c['tag']}`" for c in database.get_all_clubs()]) or "brak"
        return False, f"❌ Nie znaleziono klubu o tagu `{c_tag}`.\n> Dostępne kluby: {all_tags}", None

    is_auth = is_admin_or_federation(author) or is_club_board_or_owner(author, c_tag)
    if not is_auth:
        return False, "❌ Brak uprawnień. Wymagany Zarząd Federacji, Administrator lub Władze Klubu.", None

    if wlasciciel is None and zarzad is None:
        rep_id = club.get("reprezentant_dc")
        board_ids = club.get("board_ids") or []
        r_board = club.get("role_board_id")

        rep_str = f"<@{rep_id}>" if rep_id else "*Brak przypisanego reprezentanta*"
        board_mentions = [f"<@{bid}>" for bid in board_ids if bid != rep_id]
        board_str = ", ".join(board_mentions) if board_mentions else "*Brak innych osób w zarządzie*"
        role_str = f"<@&{r_board}>" if r_board else "*Brak roli zarządu*"

        embed = discord.Embed(
            title=f"👔 Władze Klubu: {club.get('name', c_tag)} [{c_tag}]",
            description=f"> Oficjalny skład zarządu w bazie danych.\n> Rola Discord: {role_str}",
            color=0x2b5278
        )
        embed.add_field(name="👑 Właściciel / Reprezentant", value=rep_str, inline=False)
        embed.add_field(name="💼 Członkowie Zarządu", value=board_str, inline=False)
        embed.add_field(
            name="ℹ️ Jak zmienić lub usunąć osoby bez usuwania klubu/kontraktów?",
            value=(
                f"• **Zmiana właściciela:** `/klub zarzad tag:{c_tag} wlasciciel:@Uzytkownik`\n"
                f"• **Zmiana zarządu:** `/klub zarzad tag:{c_tag} zarzad:@Osoba1 @Osoba2`\n"
                f"• **Usunięcie właściciela:** `/klub zarzad tag:{c_tag} wlasciciel:brak`\n"
                f"• **Usunięcie zarządu:** `/klub zarzad tag:{c_tag} zarzad:brak`\n"
                f"• **Prefiks:** `!klub_zarzad {c_tag} brak brak`\n"
                f"• **Biuro Składów:** Przycisk *Zarządzanie klubem* w panelu wniosków"
            ),
            inline=False
        )
        embed.set_footer(text=f"{league_config.league_name()}")
        return True, "", embed

    if wlasciciel is not None:
        if not (is_admin_or_federation(author) or club.get("reprezentant_dc") == author.id):
            return False, "❌ Tylko Zarząd Federacji, Administrator lub obecny Właściciel może modyfikować właściciela klubu.", None

    change_owner = (wlasciciel is not None)
    change_board = (zarzad is not None)

    c_old = club
    old_rep = c_old.get("reprezentant_dc")
    old_founder_ids = extract_ids(c_old.get("founder_txt", "") or "")
    if not old_founder_ids and old_rep:
        old_founder_ids = [old_rep]

    old_board_extracted = extract_ids(c_old.get("board_txt", "") or "")
    if not old_board_extracted and c_old.get("board_ids"):
        old_board_extracted = [bid for bid in c_old["board_ids"] if bid not in old_founder_ids]

    new_rep_id = database.clubs._UNSET
    new_founder_txt = database.clubs._UNSET
    target_founder_ids = old_founder_ids

    if change_owner:
        w_clean = wlasciciel.strip()
        if w_clean.lower() in CLEAR_KEYWORDS:
            new_rep_id = None
            new_founder_txt = ""
            target_founder_ids = []
        else:
            extracted = extract_ids(w_clean)
            new_rep_id = extracted[0] if extracted else None
            new_founder_txt = w_clean
            target_founder_ids = extracted

    new_board_txt = database.clubs._UNSET
    target_board_extracted = old_board_extracted

    if change_board:
        z_clean = zarzad.strip()
        if z_clean.lower() in CLEAR_KEYWORDS:
            new_board_txt = ""
            target_board_extracted = []
        else:
            extracted = extract_ids(z_clean)
            new_board_txt = z_clean
            target_board_extracted = extracted

    if change_owner or change_board:
        total_board_ids = list(dict.fromkeys(target_founder_ids + target_board_extracted))
        pass_board_ids = total_board_ids
    else:
        total_board_ids = c_old.get("board_ids", [])
        pass_board_ids = database.clubs._UNSET

    database.update_club_full(
        old_tag=c_tag,
        new_founder_txt=new_founder_txt,
        new_board_txt=new_board_txt,
        new_board_ids=pass_board_ids,
        new_rep_id=new_rep_id
    )

    roles_added = []
    roles_removed = []
    if guild:
        r_board_id = c_old.get("role_board_id")
        r_board = guild.get_role(r_board_id) if r_board_id else None
        if r_board and (change_owner or change_board):
            old_all_board = set(c_old.get("board_ids", []))
            if old_rep:
                old_all_board.add(old_rep)
            target_all_board = set(total_board_ids)

            for uid in (old_all_board - target_all_board):
                m = await get_or_fetch_member(guild, uid)
                if m:
                    try:
                        await m.remove_roles(r_board, reason=f"Aktualizacja władz klubu {c_tag}")
                        roles_removed.append(f"<@{uid}>")
                    except Exception as e:
                        print(f"[MarketCog] Błąd odebrania roli zarządu {uid}: {e}")

            for uid in (target_all_board - old_all_board):
                m = await get_or_fetch_member(guild, uid)
                if m:
                    try:
                        await m.add_roles(r_board, reason=f"Aktualizacja władz klubu {c_tag}")
                        roles_added.append(f"<@{uid}>")
                    except Exception as e:
                        print(f"[MarketCog] Błąd nadania roli zarządu {uid}: {e}")

    kom_channel_id = league_config.channel_komunikaty_id() or CHANNEL_KOMUNIKATY_ID
    if guild and kom_channel_id:
        kom_ch = guild.get_channel(kom_channel_id)
        if kom_ch:
            try:
                author_mention = author.mention if hasattr(author, "mention") else f"<@{author.id}>"
                await kom_ch.send(
                    f"👔 **AKTUALIZACJA WŁADZ KLUBU!** Dane klubu **{club.get('name', c_tag)}** (`{c_tag}`) zostały zaktualizowane przez {author_mention}.",
                    allowed_mentions=discord.AllowedMentions.none()
                )
            except Exception as e:
                print(f"[MarketCog] Błąd wysyłania komunikatu: {e}")

    author_mention = author.mention if hasattr(author, "mention") else f"<@{author.id}>"
    embed = discord.Embed(
        title=f"✅ Zaktualizowano Władze Klubu: {club.get('name', c_tag)} [{c_tag}]",
        description=f"> Zmiany zatwierdzone przez {author_mention}.\n> Żadne kontrakty ani zawodnicy nie zostali zmodyfikowani.",
        color=0x2ecc71
    )
    if change_owner:
        rep_txt = f"<@{new_rep_id}>" if new_rep_id else "*Brak (usunięto)*"
        embed.add_field(name="👑 Nowy Właściciel / Reprezentant", value=rep_txt, inline=True)
    if change_board:
        b_txt = ", ".join(f"<@{uid}>" for uid in target_board_extracted) if target_board_extracted else "*Brak (usunięto)*"
        embed.add_field(name="💼 Nowy Zarząd", value=b_txt, inline=True)
    if roles_added:
        embed.add_field(name="➕ Nadano rolę zarządu", value=", ".join(roles_added), inline=False)
    if roles_removed:
        embed.add_field(name="➖ Odebrano rolę zarządu", value=", ".join(roles_removed), inline=False)
    embed.set_footer(text=f"{league_config.league_name()}")
    return True, "", embed


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

        @klub_group.command(name="zarzad", description="[Admin / Zarząd] Zarządzanie władzami klubu (właściciel, zarząd) bez ruszania kadr")
        @app_commands.describe(
            tag="Skrót (tag) klubu, np. LEG, WIS",
            wlasciciel="Nowy właściciel (@Wzmianka, ID lub 'brak'/'usun' aby wyczyścić)",
            zarzad="Członkowie zarządu (@Wzmianki, ID lub 'brak'/'usun' aby wyczyścić)"
        )
        @app_commands.autocomplete(tag=club_tag_autocomplete)
        async def slash_klub_zarzad(interaction: discord.Interaction, tag: str, wlasciciel: str = None, zarzad: str = None):
            success, err_msg, embed = await _update_club_board_data(
                guild=interaction.guild,
                author=interaction.user,
                tag=tag,
                wlasciciel=wlasciciel,
                zarzad=zarzad
            )
            if not success:
                return await interaction.response.send_message(err_msg, ephemeral=True)
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

    @commands.command(name='klub_zarzad', aliases=['zarzad_klubu', 'klubzarzad'])
    async def cmd_klub_zarzad(self, ctx, tag: str = None, wlasciciel: str = None, *, zarzad: str = None):
        """
        Zarządzanie władzami klubu (bez dotykania kontraktów i zawodników):
        !klub_zarzad LEG                            -> Pokazuje obecne władze i instrukcję
        !klub_zarzad LEG @NowyWlasciciel            -> Zmienia właściciela
        !klub_zarzad LEG brak                       -> Usuwa przypisanego właściciela
        !klub_zarzad LEG bez_zmian @Zarzad1 @Zarzad2 -> Zmienia członków zarządu
        !klub_zarzad LEG brak brak                  -> Czyści właściciela i zarząd
        """
        if not tag:
            return await ctx.reply("❌ Podaj tag klubu, np. `!klub_zarzad LEG`.")
        if wlasciciel and wlasciciel.lower() in ("bez_zmian", "bezzmian", "skip", "none_owner"):
            wlasciciel = None
        success, err_msg, embed = await _update_club_board_data(
            guild=ctx.guild,
            author=ctx.author,
            tag=tag,
            wlasciciel=wlasciciel,
            zarzad=zarzad
        )
        if not success:
            return await ctx.reply(err_msg)
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MarketCog(bot))
