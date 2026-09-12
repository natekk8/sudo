import discord
from discord import ui
import database
from config import MAX_PLAYERS_PER_CLUB
import utils.league_config as league_config
from utils.helpers import build_squad_bar, format_expiry_discord, clean_player_name


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
        for c in page_clubs:
            count = database.get_club_player_count(c["tag"])
            options.append(discord.SelectOption(
                label=f"{c['name']} ({c['tag']})"[:100],
                value=c["tag"],
                description=f"Skład: {count}/{MAX_PLAYERS_PER_CLUB}",
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
            lines = []
            for p in players:
                clean_n = clean_player_name(p.get("name", ""), p.get("discord_id"))
                name_d = f"**{clean_n}** (<@{p['discord_id']}>)" if p.get("discord_id") else f"**{clean_n}**"
                typ = "⏱️ Wyp." if p.get("contract_type") == "WYPOZYCZENIE" else "📄"
                expires = format_expiry_discord(p.get("expires_at"))
                klauz = p.get("clause", "Brak")
                lines.append(f"{typ} {name_d} · do {expires} · Klauzula: `{klauz}`")
            embed.add_field(name="Zawodnicy", value="\n".join(lines), inline=False)
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
    """Panel Rynek Transferowy & Baza Graczy (Wiadomość 2)."""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Szukam Klubu", style=discord.ButtonStyle.success,
               emoji="🙋", custom_id="rynek_szukam_klubu")
    async def b_szukam_klubu(self, interaction: discord.Interaction, button: ui.Button):
        user = interaction.user

        existing = database.get_player_by_discord_id(user.id)
        if existing and existing.get("club_tag"):
            return await interaction.response.send_message(
                f"❌ Jesteś już zarejestrowany w klubie **`{existing['club_tag']}`**!\n"
                "Aby szukać nowego klubu, zakończ obecny kontrakt lub zostań transferowanym.",
                ephemeral=True
            )

        if database.is_free_agent(user.id):
            database.remove_free_agent(user.id)
            await interaction.response.send_message(
                "✅ Usunięto Cię z listy wolnych agentów. Nie szukasz już klubu.",
                ephemeral=True
            )
        else:
            database.register_free_agent(user.id, user.display_name)
            await interaction.response.send_message(
                "✅ Zarejestrowano Cię jako **wolnego agenta**! Jesteś widoczny na giełdzie graczy.\n"
                "Ponowne kliknięcie tego przycisku usunie Cię z listy.",
                ephemeral=True
            )

    @ui.button(label="Szukam Zawodnika", style=discord.ButtonStyle.primary,
               emoji="🔍", custom_id="rynek_szukam_zawodnika")
    async def b_szukam_zawodnika(self, interaction: discord.Interaction, button: ui.Button):
        agents, total = database.get_free_agents_paginated(_MAX_DISPLAY_AGENTS)

        if not agents:
            return await interaction.response.send_message(
                "📋 **Giełda Wolnych Agentów jest obecnie pusta.**\n"
                "> Żaden gracz nie zgłosił się jako wolny agent.",
                ephemeral=True
            )

        lines = [f"• <@{a['discord_id']}> ({a.get('player_name', '?')})" for a in agents]
        showed = len(agents)
        footer_txt = f"Wyświetlono {showed} z {total} wolnych agentów"

        embed = discord.Embed(
            title=f"📋 Giełda Wolnych Agentów ({total} graczy)",
            description="\n".join(lines),
            color=0x3498db
        )
        embed.set_footer(text=footer_txt)
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
