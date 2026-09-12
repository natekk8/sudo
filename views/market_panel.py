import discord
from discord import ui
import database
from config import MAX_PLAYERS_PER_CLUB
from utils.helpers import build_squad_bar, format_expiry_discord, is_club_board_or_owner

class KlubSelect(ui.Select):
    """Menu wyboru klubu do podglądu składu."""

    def __init__(self, clubs: list):
        options = []
        for c in clubs[:25]:  # Discord max 25 opcji
            label = f"{c['name']} ({c['tag']})"
            count = database.get_club_player_count(c["tag"])
            desc = f"Skład: {count}/{MAX_PLAYERS_PER_CLUB}"
            options.append(discord.SelectOption(
                label=label[:100],
                value=c["tag"],
                description=desc,
                emoji="⚽"
            ))
        if not options:
            options.append(discord.SelectOption(label="Brak zarejestrowanych klubów", value="__none__"))
        super().__init__(
            placeholder="Wybierz klub...",
            options=options,
            custom_id="rynek_select_klub"
        )

    async def callback(self, interaction: discord.Interaction):
        tag = self.values[0]
        if tag == "__none__":
            return await interaction.response.send_message(
                "❌ Brak zarejestrowanych klubów.", ephemeral=True
            )

        club = database.get_club(tag)
        if not club:
            return await interaction.response.send_message(
                "❌ Nie znaleziono klubu.", ephemeral=True
            )

        players = database.get_club_players(tag)
        count = len(players)

        embed = discord.Embed(
            title=f"⚽ {club['name']} (`{tag}`)",
            color=0x2b2d31
        )
        embed.add_field(
            name="Skład kadry",
            value=build_squad_bar(count, MAX_PLAYERS_PER_CLUB),
            inline=False
        )

        if players:
            player_lines = []
            for p in players:
                name_display = f"<@{p['discord_id']}>" if p.get("discord_id") else f"**{p['name']}**"
                typ = "⏱️ Wyp." if p.get("contract_type") == "WYPOZYCZENIE" else "📄"
                expires = format_expiry_discord(p.get("expires_at"))
                klauz = p.get("clause", "Brak")
                player_lines.append(f"{typ} {name_display} · do {expires} · Klauzula: `{klauz}`")
            embed.add_field(name="Zawodnicy", value="\n".join(player_lines), inline=False)
        else:
            embed.add_field(name="Zawodnicy", value="*Brak zarejestrowanych zawodników.*", inline=False)

        # Zarząd
        founder_txt = club.get("founder_txt") or ""
        board_txt = club.get("board_txt") or ""
        board_info = []
        if founder_txt and founder_txt.strip():
            board_info.append(f"Założyciel: {founder_txt}")
        if board_txt and board_txt.strip() and board_txt.lower() != "brak":
            board_info.append(f"Zarząd: {board_txt}")
        if board_info:
            embed.add_field(name="Władze klubu", value="\n".join(board_info), inline=False)

        embed.set_footer(text=f"Rynek Transferowy · Liga")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class WidokRynkuTransferowego(ui.View):
    """Panel Rynek Transferowy & Baza Graczy (Wiadomość 2)."""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Szukam Klubu", style=discord.ButtonStyle.success,
               emoji="🙋", custom_id="rynek_szukam_klubu")
    async def b_szukam_klubu(self, interaction: discord.Interaction, button: ui.Button):
        user = interaction.user

        # Sprawdź czy gracz nie jest już w klubie
        existing = database.get_player_by_discord_id(user.id)
        if existing and existing.get("club_tag"):
            return await interaction.response.send_message(
                f"❌ Jesteś już zarejestrowany w klubie **`{existing['club_tag']}`**!\n"
                "Aby znaleźć nowy klub, musisz najpierw zakończyć obecny kontrakt lub zostać transferowanym.",
                ephemeral=True
            )

        # Sprawdź czy już zarejestrowany na giełdzie
        if database.is_free_agent(user.id):
            database.remove_free_agent(user.id)
            return await interaction.response.send_message(
                "✅ Usunięto Cię z listy wolnych agentów. Nie szukasz już klubu.",
                ephemeral=True
            )

        # Zarejestruj jako wolny agent
        display_name = user.display_name
        database.register_free_agent(user.id, display_name)
        await interaction.response.send_message(
            f"✅ Zostałeś zarejestrowany jako **wolny agent**!\n"
            f"> Prezesi i zarządy klubów zobaczą Cię w sekcji **Szukam Zawodnika**.\n"
            f"> Ponowne kliknięcie tego przycisku usunie Cię z listy.",
            ephemeral=True
        )

    @ui.button(label="Szukam Zawodnika", style=discord.ButtonStyle.primary,
               emoji="🔍", custom_id="rynek_szukam_zawodnika")
    async def b_szukam_zawodnika(self, interaction: discord.Interaction, button: ui.Button):
        agents = database.get_all_free_agents()

        if not agents:
            return await interaction.response.send_message(
                "📋 **Giełda Wolnych Agentów jest obecnie pusta.**\n"
                "> Żaden gracz nie zgłosił się jako wolny agent.",
                ephemeral=True
            )

        lines = []
        for a in agents:
            dc_id = a.get("discord_id")
            name = a.get("player_name", "Nieznany")
            lines.append(f"• <@{dc_id}> ({name})")

        embed = discord.Embed(
            title=f"📋 Giełda Wolnych Agentów ({len(agents)} graczy)",
            description="\n".join(lines),
            color=0x3498db
        )
        embed.set_footer(text="Skontaktuj się z graczem lub złóż wniosek Podpisania Gracza w Biurze Federacji.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Składy Drużyn", style=discord.ButtonStyle.secondary,
               emoji="📋", custom_id="rynek_sklady_druzyn")
    async def b_sklady(self, interaction: discord.Interaction, button: ui.Button):
        clubs = database.get_all_clubs()

        if not clubs:
            return await interaction.response.send_message(
                "❌ Brak zarejestrowanych klubów.", ephemeral=True
            )

        view = ui.View(timeout=120)
        view.add_item(KlubSelect(clubs))
        await interaction.response.send_message(
            "⚽ **Podgląd Składu Drużyn** – wybierz klub z listy:",
            view=view,
            ephemeral=True
        )
