"""
views/transfer_list.py
======================
Lista Transferowa: interaktywne (ephemeral) UI do wystawiania własnych zawodników
oraz embed z aktualną listą.

Uprawnienia:
  • Zarząd / właściciel klubu → tylko zawodnicy SWOJEGO klubu,
  • Zarząd Federacji / Administrator → zawodnicy dowolnego klubu.
"""
import discord
from discord import ui

import database
import utils.league_config as league_config
from utils.helpers import (
    is_club_board_or_owner, parse_price_input, format_price, format_expiry_discord,
    clean_player_name, get_komunikaty_channel, send_dm,
)

_VIEW_TIMEOUT = 180
_PAGE_SIZE = 23  # + opcje "poprzednia"/"następna" = 25


# ─────────────────────────────────────────────────────────────────────────────
# Pomocnicze
# ─────────────────────────────────────────────────────────────────────────────

def manageable_clubs(user) -> list:
    """Kluby, którymi użytkownik może zarządzać listą transferową."""
    return [c for c in database.get_all_clubs() if is_club_board_or_owner(user, c["tag"])]


def listable_players(club_tag: str) -> list:
    """Zawodnicy klubu, których klub może wystawić (bez wypożyczonych z innego klubu)."""
    players = [p for p in database.get_club_players(club_tag)
               if p.get("contract_type") != "WYPOZYCZENIE"]
    players.sort(key=lambda p: (p.get("name") or "").lower())
    return players


class _PagedSelect(ui.Select):
    """Select z automatycznym stronicowaniem (limit Discorda: 25 opcji)."""

    def __init__(self, entries: list, placeholder: str, on_pick, page: int = 0):
        # entries: [(label, value, description, emoji)]
        self.entries = entries
        self.on_pick = on_pick
        self.page = page
        self.placeholder_txt = placeholder

        if len(entries) <= 25:
            chunk, prev_p, next_p = entries, False, False
        else:
            start = page * _PAGE_SIZE
            chunk = entries[start:start + _PAGE_SIZE]
            prev_p = page > 0
            next_p = start + _PAGE_SIZE < len(entries)

        options = []
        if prev_p:
            options.append(discord.SelectOption(label="◀ Poprzednia strona", value=f"__page_{page - 1}__"))
        for label, value, desc, emoji in chunk:
            options.append(discord.SelectOption(
                label=label[:100], value=value[:100], description=(desc or None) and desc[:100], emoji=emoji))
        if next_p:
            options.append(discord.SelectOption(label="▶ Następna strona", value=f"__page_{page + 1}__"))
        if not options:
            options.append(discord.SelectOption(label="Brak pozycji", value="__none__"))

        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "__none__":
            return await interaction.response.defer()
        if val.startswith("__page_"):
            new_page = int(val[7:-2])
            v = ui.View(timeout=_VIEW_TIMEOUT)
            v.add_item(_PagedSelect(self.entries, self.placeholder_txt, self.on_pick, new_page))
            return await interaction.response.edit_message(view=v)
        await self.on_pick(interaction, val)


def _club_name(tag: str) -> str:
    c = database.get_club(tag)
    return c.get("name", tag) if c else tag


# ─────────────────────────────────────────────────────────────────────────────
# Punkt wejścia (przycisk „Zaktualizuj Listę Transferową")
# ─────────────────────────────────────────────────────────────────────────────

async def proces_listy_transferowej(interaction: discord.Interaction):
    clubs = manageable_clubs(interaction.user)
    if not clubs:
        return await interaction.response.send_message(
            "❌ **Brak uprawnień.**\n"
            "> Listę transferową może aktualizować wyłącznie **Zarząd klubu** (swoich zawodników) "
            "lub **Zarząd Federacji**.",
            ephemeral=True)

    if len(clubs) == 1:
        return await _show_players(interaction, clubs[0]["tag"], edit=False)

    counts = database.get_club_player_counts()
    entries = [(f"{c['name']} ({c['tag']})", c["tag"], f"Zawodników: {counts.get(c['tag'], 0)}", "⚽")
               for c in clubs]

    async def on_pick(inter, tag):
        await _show_players(inter, tag, edit=True)

    v = ui.View(timeout=_VIEW_TIMEOUT)
    v.add_item(_PagedSelect(entries, "Wybierz klub...", on_pick))
    await interaction.response.send_message(
        "📋 **Lista Transferowa** – wybierz klub, którego zawodnika chcesz wystawić:",
        view=v, ephemeral=True)


async def _show_players(interaction: discord.Interaction, club_tag: str, edit: bool):
    players = listable_players(club_tag)
    if not players:
        text = f"❌ Klub `{club_tag}` nie ma zawodników, których można wystawić na listę transferową."
        if edit:
            return await interaction.response.edit_message(content=text, view=None, embed=None)
        return await interaction.response.send_message(text, ephemeral=True)

    entries = []
    for p in players:
        listed = database.get_transfer_list_entry(p["name"])
        clean_n = clean_player_name(p.get("name"), p.get("discord_id"))
        if listed:
            entries.append((clean_n, p["name"], f"Na liście · cena: {format_price(listed['price'])}", "📋"))
        else:
            entries.append((clean_n, p["name"], "Nie wystawiony", "👤"))

    async def on_pick(inter, player_name):
        await _show_player_actions(inter, club_tag, player_name)

    v = ui.View(timeout=_VIEW_TIMEOUT)
    v.add_item(_PagedSelect(entries, "Wybierz zawodnika...", on_pick))
    text = (f"📋 **Lista Transferowa · {_club_name(club_tag)} (`{club_tag}`)**\n"
            "> Wybierz zawodnika, którego chcesz wystawić, zmienić mu cenę lub zdjąć z listy.")
    if edit:
        await interaction.response.edit_message(content=text, embed=None, view=v)
    else:
        await interaction.response.send_message(text, view=v, ephemeral=True)


def _player_embed(club_tag: str, player: dict, listed: dict | None) -> discord.Embed:
    clean_n = clean_player_name(player.get("name"), player.get("discord_id"))
    embed = discord.Embed(title=f"📋 {clean_n}", color=0x3498db if not listed else 0xf1c40f)
    embed.add_field(name="Klub", value=f"`{club_tag}`", inline=True)
    embed.add_field(name="Umowa do", value=format_expiry_discord(player.get("expires_at")), inline=True)
    embed.add_field(name="Klauzula", value=f"`{player.get('clause') or 'Brak'}`", inline=True)
    if listed:
        status = f"📋 **Na liście transferowej** · cena: `{format_price(listed['price'])}`"
        if listed.get("note"):
            status += f"\n> {listed['note']}"
    else:
        status = "Zawodnik **nie jest** na liście transferowej."
    embed.add_field(name="Status", value=status, inline=False)
    embed.set_footer(text=f"Lista Transferowa • {league_config.league_name()}")
    return embed


async def _show_player_actions(interaction: discord.Interaction, club_tag: str, player_name: str):
    player = database.get_player(player_name)
    if not player or (player.get("club_tag") or "").upper() != club_tag.upper():
        return await interaction.response.edit_message(
            content="❌ Ten zawodnik nie należy już do tego klubu.", embed=None, view=None)
    listed = database.get_transfer_list_entry(player["name"])
    await interaction.response.edit_message(
        content=None, embed=_player_embed(club_tag, player, listed),
        view=PlayerActionView(club_tag, player["name"], bool(listed)))


# ─────────────────────────────────────────────────────────────────────────────
# Widok akcji + modal ceny
# ─────────────────────────────────────────────────────────────────────────────

class PlayerActionView(ui.View):
    def __init__(self, club_tag: str, player_name: str, is_listed: bool):
        super().__init__(timeout=_VIEW_TIMEOUT)
        self.club_tag = club_tag
        self.player_name = player_name
        if not is_listed:
            self.b_remove.disabled = True
        self.b_set.label = "Zmień cenę" if is_listed else "Wystaw na listę"

    @ui.button(label="Wystaw na listę", style=discord.ButtonStyle.success, emoji="💰", row=0)
    async def b_set(self, interaction: discord.Interaction, button: ui.Button):
        if not is_club_board_or_owner(interaction.user, self.club_tag):
            return await interaction.response.send_message("❌ Brak uprawnień do tego klubu.", ephemeral=True)
        existing = database.get_transfer_list_entry(self.player_name)
        await interaction.response.send_modal(PriceModal(self.club_tag, self.player_name, existing))

    @ui.button(label="Zdejmij z listy", style=discord.ButtonStyle.danger, emoji="🗑️", row=0)
    async def b_remove(self, interaction: discord.Interaction, button: ui.Button):
        if not is_club_board_or_owner(interaction.user, self.club_tag):
            return await interaction.response.send_message("❌ Brak uprawnień do tego klubu.", ephemeral=True)
        player = database.get_player(self.player_name)
        if database.remove_from_transfer_list(self.player_name):
            name = clean_player_name(self.player_name, player.get("discord_id") if player else None)
            await _announce(interaction.client, interaction.guild,
                            f"🗑️ **{name}** (`{self.club_tag}`) został **zdjęty z listy transferowej**.")
            await interaction.response.edit_message(
                content=f"✅ **{name}** został zdjęty z listy transferowej.", embed=None, view=None)
        else:
            await interaction.response.edit_message(
                content="ℹ️ Ten zawodnik nie był już na liście transferowej.", embed=None, view=None)

    @ui.button(label="Wróć", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
    async def b_back(self, interaction: discord.Interaction, button: ui.Button):
        await _show_players(interaction, self.club_tag, edit=True)


class PriceModal(ui.Modal):
    def __init__(self, club_tag: str, player_name: str, existing: dict | None = None):
        super().__init__(title="Lista Transferowa – cena", timeout=300)
        self.club_tag = club_tag
        self.player_name = player_name
        self.existing = existing
        self.price = ui.TextInput(
            label="Cena (0 / Brak = do negocjacji)", placeholder="np. 15000",
            default=str(existing["price"]) if existing else None,
            required=True, max_length=15)
        self.note = ui.TextInput(
            label="Uwagi (opcjonalnie)", placeholder="np. pozycja, oczekiwania",
            default=(existing or {}).get("note"),
            required=False, max_length=80, style=discord.TextStyle.short)
        self.add_item(self.price)
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        if not is_club_board_or_owner(user, self.club_tag):
            return await interaction.response.send_message("❌ Brak uprawnień do tego klubu.", ephemeral=True)

        player = database.get_player(self.player_name)
        if (not player or (player.get("club_tag") or "").upper() != self.club_tag.upper()
                or player.get("contract_type") == "WYPOZYCZENIE"):
            return await interaction.response.send_message(
                "❌ Ten zawodnik nie należy już do Twojego klubu lub jest wypożyczony.", ephemeral=True)

        price = parse_price_input(self.price.value)
        if price is None:
            return await interaction.response.send_message(
                "❌ Niepoprawna cena. Wpisz liczbę (np. `15000`) albo `0` / `Brak` dla „do negocjacji”.",
                ephemeral=True)

        old_price = self.existing["price"] if self.existing else None
        was_listed = database.add_to_transfer_list(
            player["name"], self.club_tag, price,
            discord_id=player.get("discord_id"), listed_by=user.id, note=self.note.value)

        clean_n = clean_player_name(player["name"], player.get("discord_id"))
        c_nazwa = _club_name(self.club_tag)
        if was_listed and old_price is not None and old_price != price:
            ann = (f"🔄 **ZMIANA CENY NA LIŚCIE TRANSFEROWEJ:** **{clean_n}** (**{c_nazwa}** · `{self.club_tag}`)\n"
                   f"> Cena: `{format_price(old_price)}` ➔ `{format_price(price)}`")
        elif was_listed:
            ann = None  # tylko zmiana notatki – bez hałasu na komunikatach
        else:
            ann = (f"📋 **NOWY ZAWODNIK NA LIŚCIE TRANSFEROWEJ:** **{clean_n}** (**{c_nazwa}** · `{self.club_tag}`)\n"
                   f"> Cena: `{format_price(price)}`"
                   + (f" · {self.note.value.strip()}" if self.note.value and self.note.value.strip() else ""))
        if ann:
            await _announce(interaction.client, interaction.guild, ann)

        if not was_listed and player.get("discord_id"):
            await send_dm(interaction.client, player["discord_id"],
                          f"📋 Klub `{self.club_tag}` wystawił Cię na **listę transferową** "
                          f"(cena: `{format_price(price)}`).")

        listed = database.get_transfer_list_entry(player["name"])
        embed = _player_embed(self.club_tag, player, listed)
        embed.title = f"✅ {'Zaktualizowano' if was_listed else 'Wystawiono'}: {clean_n}"
        embed.color = 0x2ecc71
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"[PriceModal] Błąd: {error}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Wystąpił błąd. Spróbuj ponownie.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Wystąpił błąd. Spróbuj ponownie.", ephemeral=True)
        except Exception:
            pass


async def _announce(client, guild, text: str):
    channel = await get_komunikaty_channel(client, guild)
    if channel:
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except Exception as e:
            print(f"[TransferList] Błąd ogłoszenia: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Podgląd listy („Szukam Zawodnika")
# ─────────────────────────────────────────────────────────────────────────────

_DESC_LIMIT = 3600


def build_transfer_list_embed() -> discord.Embed:
    entries = database.get_transfer_list()
    free_agents, fa_total = database.get_free_agents_paginated(10)

    embed = discord.Embed(
        title=f"📋 Lista Transferowa ({len(entries)})",
        color=0xf1c40f if entries else 0x2b2d31)

    if entries:
        lines, used = [], 0
        for i, e in enumerate(entries):
            clean_n = clean_player_name(e.get("player_name"), e.get("discord_id"))
            who = f"**{clean_n}**" + (f" (<@{e['discord_id']}>)" if e.get("discord_id") else "")
            line = (f"• {who} · `{e['club_tag']}` · 💰 `{format_price(e['price'])}`")
            if e.get("note"):
                line += f" · *{e['note']}*"
            if used + len(line) + 1 > _DESC_LIMIT:
                lines.append(f"*…oraz {len(entries) - i} kolejnych zawodników.*")
                break
            lines.append(line)
            used += len(line) + 1
        embed.description = "\n".join(lines)
    else:
        embed.description = ("*Lista transferowa jest obecnie pusta.*\n"
                             "> Zarządy klubów mogą wystawiać zawodników przyciskiem "
                             "**Zaktualizuj Listę Transferową**.")

    if free_agents:
        fa_lines, used = [], 0
        for a in free_agents:
            line = f"• <@{a['discord_id']}> ({clean_player_name(a.get('player_name'), a['discord_id'])})"
            if used + len(line) + 1 > 950:
                break
            fa_lines.append(line)
            used += len(line) + 1
        extra = f"\n*…łącznie {fa_total}*" if fa_total > len(fa_lines) else ""
        embed.add_field(name=f"🆓 Wolni agenci ({fa_total})", value="\n".join(fa_lines) + extra, inline=False)

    embed.set_footer(text=f"Najtańsi na górze • {league_config.league_name()}")
    return embed
