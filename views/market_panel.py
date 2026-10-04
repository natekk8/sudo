import discord
from discord import ui
import database
import utils.league_config as league_config
from utils.helpers import build_squad_bar, format_expiry_discord, clean_player_name, format_price


_MAX_DISPLAY_AGENTS = 25


class KlubSelectPage(ui.Select):
    """Stronicowane menu wyboru klubu (do 25 opcji na stronę)."""

    def __init__(self, clubs: list, page: int = 0):
        self.all_clubs = clubs
        self.page = page
        per_page = 24  # 24 + "Następna strona" = 25
        start = page * per_page
        end = start + per_page
        page_clubs = clubs[start:end]
        has_next = end < len(clubs)

        options = []
        counts = database.get_club_player_counts()
        for c in page_clubs:
            count = counts.get(c["tag"].upper(), 0)
            options.append(discord.SelectOption(
                label=f"{c['name']} ({c['tag']})"[:100],
                value=c["tag"],
                description=f"Skład: {count}/{league_config.max_players()}",
                emoji="⚽"
            ))
        if has_next:
            options.append(discord.SelectOption(
                label=f"▶ Następna strona ({end + 1}–{min(end + per_page, len(clubs))} z {len(clubs)})",
                value=f"__page_{page + 1}__",
                emoji="➡️"
            ))
        if not options:
            options.append(discord.SelectOption(label="Brak zarejestrowanych klubów", value="__none__"))

        super().__init__(placeholder="Wybierz klub...", options=options,
                         custom_id=f"rynek_select_klub_p{page}")

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "__none__":
            return await interaction.response.send_message("❌ Brak zarejestrowanych klubów.", ephemeral=True)

        if val.startswith("__page_"):
            page_num = int(val.replace("__page_", ""))
            v = ui.View(timeout=120)
            v.add_item(KlubSelectPage(self.all_clubs, page_num))
            return await interaction.response.edit_message(
                content="⚽ **Podgląd Składu Drużyn** – wybierz klub z listy:",
                view=v
            )

        club = database.get_club(val)
        if not club:
            return await interaction.response.send_message("❌ Nie znaleziono klubu.", ephemeral=True)

        players = database.get_club_players(val)
        count = len(players)

        embed = discord.Embed(title=f"⚽ {club['name']} (`{val}`)", color=0x2b2d31)
        embed.add_field(name="Skład kadry", value=build_squad_bar(count, league_config.max_players()), inline=False)

        if players:
            listed = {e["player_name"].lower(): e for e in database.get_transfer_list()
                      if e["club_tag"].upper() == val.upper()}
            lines = []
            for p in players:
                clean_n = clean_player_name(p.get("name", ""), p.get("discord_id"))
                name_d = f"**{clean_n}** (<@{p['discord_id']}>)" if p.get("discord_id") else f"**{clean_n}**"
                typ = "⏱️ Wyp." if p.get("contract_type") == "WYPOZYCZENIE" else "📄"
                expires = format_expiry_discord(p.get("expires_at"))
                klauz = p.get("clause", "Brak")
                line = f"{typ} {name_d} · do {expires} · Klauzula: `{klauz}`"
                entry = listed.get((p.get("name") or "").lower())
                if entry:
                    line += f" · 📋 **Na sprzedaż: `{format_price(entry['price'])}`**"
                lines.append(line)

            # Pole embeda: max 1024 znaków – dzielimy na kilka pól przy dużych kadrach
            chunk, size, part = [], 0, 1
            for ln in lines:
                if size + len(ln) + 1 > 1000 and chunk:
                    embed.add_field(name="Zawodnicy" if part == 1 else "Zawodnicy (cd.)",
                                    value="\n".join(chunk), inline=False)
                    chunk, size, part = [], 0, part + 1
                chunk.append(ln)
                size += len(ln) + 1
            if chunk:
                embed.add_field(name="Zawodnicy" if part == 1 else "Zawodnicy (cd.)",
                                value="\n".join(chunk), inline=False)
        else:
            embed.add_field(name="Zawodnicy", value="*Brak zarejestrowanych zawodników.*", inline=False)

        if club.get("founder_txt") or club.get("board_txt"):
            board_info = []
            if club.get("founder_txt"): board_info.append(f"Właściciel: {club['founder_txt']}")
            if club.get("board_txt") and club["board_txt"].lower() != "brak":
                board_info.append(f"Zarząd: {club['board_txt']}")
            if board_info:
                embed.add_field(name="Władze klubu", value="\n".join(board_info), inline=False)

        embed.set_footer(text=f"Rynek Transferowy • {league_config.league_name()}")
        await interaction.response.edit_message(embed=embed, view=None)



class WidokRynkuTransferowego(ui.View):
    """Panel Rynek Transferowy: Lista Transferowa & Składy Drużyn (Wiadomość 2)."""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Zaktualizuj Listę Transferową", style=discord.ButtonStyle.success,
               emoji="📝", custom_id="rynek_lista_update")
    async def b_lista_update(self, interaction: discord.Interaction, button: ui.Button):
        from views.transfer_list import proces_listy_transferowej
        await proces_listy_transferowej(interaction)

    @ui.button(label="Szukam Zawodnika", style=discord.ButtonStyle.primary,
               emoji="🔍", custom_id="rynek_szukam_zawodnika")
    async def b_szukam_zawodnika(self, interaction: discord.Interaction, button: ui.Button):
        from views.transfer_list import build_transfer_list_embed
        await interaction.response.send_message(embed=build_transfer_list_embed(), ephemeral=True)

    @ui.button(label="Składy Drużyn", style=discord.ButtonStyle.secondary,
               emoji="📋", custom_id="rynek_sklady_druzyn")
    async def b_sklady(self, interaction: discord.Interaction, button: ui.Button):
        clubs = database.get_all_clubs()
        if not clubs:
            return await interaction.response.send_message("❌ Brak zarejestrowanych klubów.", ephemeral=True)

        view = ui.View(timeout=120)
        view.add_item(KlubSelectPage(clubs, page=0))
        await interaction.response.send_message(
            "⚽ **Podgląd Składu Drużyn** – wybierz klub z listy:",
            view=view,
            ephemeral=True
        )

