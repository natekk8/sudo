import discord
from discord import ui
import database
from config import MAX_PLAYERS_PER_CLUB
from utils.helpers import build_squad_bar, format_expiry_discord

_MAX_DISPLAY_AGENTS = 25

# ─── Pozycje i platformy ───
POSITIONS = {
    "BR":  ("🧤", "Bramkarz"),
    "OBR": ("🛡️", "Obrońca"),
    "POM": ("⚙️", "Pomocnik"),
    "NAP": ("⚡", "Napastnik"),
    "UNI": ("🔄", "Wszechstronny"),
}
PLATFORMS = {
    "PC":  ("🖥️", "PC"),
    "PS":  ("🎮", "PlayStation"),
    "XBX": ("🟢", "Xbox"),
    "ALL": ("🌐", "Crossplay / Dowolna"),
}


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
        embed.add_field(name="Skład kadry", value=build_squad_bar(count, MAX_PLAYERS_PER_CLUB), inline=False)

        if players:
            lines = []
            for p in players:
                name_d = f"<@{p['discord_id']}>" if p.get("discord_id") else f"**{p['name']}**"
                typ = "⏱️ Wyp." if p.get("contract_type") == "WYPOZYCZENIE" else "📄"
                expires = format_expiry_discord(p.get("expires_at"))
                klauz = p.get("clause", "Brak")
                lines.append(f"{typ} {name_d} · do {expires} · Klauzula: `{klauz}`")
            embed.add_field(name="Zawodnicy", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Zawodnicy", value="*Brak zarejestrowanych zawodników.*", inline=False)

        if club.get("founder_txt") or club.get("board_txt"):
            board_info = []
            if club.get("founder_txt"): board_info.append(f"Założyciel: {club['founder_txt']}")
            if club.get("board_txt") and club["board_txt"].lower() != "brak":
                board_info.append(f"Zarząd: {club['board_txt']}")
            if board_info:
                embed.add_field(name="Władze klubu", value="\n".join(board_info), inline=False)

        embed.set_footer(text="Rynek Transferowy · Liga")
        await interaction.response.edit_message(embed=embed, view=None)


class AgentProfileView(ui.View):
    """Widok efemeryczny do zapisania profilu wolnego agenta (pozycja + platforma)."""

    def __init__(self, discord_id: int, player_name: str, old_position: str = "UNI", old_platform: str = "ALL"):
        super().__init__(timeout=120)
        self.discord_id = discord_id
        self.player_name = player_name
        self.selected_position = old_position
        self.selected_platform = old_platform

        # Menu pozycji
        pos_options = [
            discord.SelectOption(label=f"{emoji} {name}", value=key,
                                  default=(key == old_position))
            for key, (emoji, name) in POSITIONS.items()
        ]
        pos_select = ui.Select(placeholder="Wybierz pozycję na boisku...",
                               options=pos_options,
                               custom_id="agent_pos")
        pos_select.callback = self._pos_callback
        self.add_item(pos_select)

        # Menu platformy
        plat_options = [
            discord.SelectOption(label=f"{emoji} {name}", value=key,
                                  default=(key == old_platform))
            for key, (emoji, name) in PLATFORMS.items()
        ]
        plat_select = ui.Select(placeholder="Wybierz platformę...",
                                options=plat_options,
                                custom_id="agent_plat")
        plat_select.callback = self._plat_callback
        self.add_item(plat_select)

        save_btn = ui.Button(label="💾 Zapisz zgłoszenie na Giełdzie",
                             style=discord.ButtonStyle.success,
                             custom_id="agent_save")
        save_btn.callback = self._save_callback
        self.add_item(save_btn)

    async def _pos_callback(self, interaction: discord.Interaction):
        self.selected_position = interaction.data["values"][0]
        await interaction.response.defer()

    async def _plat_callback(self, interaction: discord.Interaction):
        self.selected_platform = interaction.data["values"][0]
        await interaction.response.defer()

    async def _save_callback(self, interaction: discord.Interaction):
        database.register_free_agent(
            discord_id=self.discord_id,
            player_name=self.player_name,
            position=self.selected_position,
            platform=self.selected_platform
        )
        pos_emoji, pos_name = POSITIONS.get(self.selected_position, ("🔄", "Wszechstronny"))
        plat_emoji, plat_name = PLATFORMS.get(self.selected_platform, ("🌐", "Dowolna"))
        await interaction.response.edit_message(
            content=(
                f"✅ Zarejestrowano Cię na **Giełdzie Wolnych Agentów**!\n"
                f"> Pozycja: {pos_emoji} **{pos_name}**\n"
                f"> Platforma: {plat_emoji} **{plat_name}**\n"
                f"Ponowne kliknięcie `🙋 Szukam Klubu` usunie Cię z listy."
            ),
            view=None
        )


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
                "Aby szukać nowego klubu, zakończ obecny kontrakt lub zostań transferowanym.",
                ephemeral=True
            )

        # Toggle: usuń jeśli już zarejestrowany
        if database.is_free_agent(user.id):
            database.remove_free_agent(user.id)
            return await interaction.response.send_message(
                "✅ Usunięto Cię z listy wolnych agentów. Nie szukasz już klubu.",
                ephemeral=True
            )

        # Nowe zgłoszenie – pokaż formularz profilu (SelectMenu, BEZ MODALU)
        fa = None  # Brak starego profilu
        view = AgentProfileView(
            discord_id=user.id,
            player_name=user.display_name,
            old_position="UNI", old_platform="ALL"
        )
        await interaction.response.send_message(
            "🙋 **Rejestracja na Giełdzie Wolnych Agentów**\n"
            "Wybierz swoją pozycję i platformę, a następnie kliknij **Zapisz**:",
            view=view,
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

        lines = []
        now_ts = int(__import__("time").time())
        for a in agents:
            dc_id = a.get("discord_id")
            name = a.get("player_name", "?")
            pos_key = a.get("position", "UNI")
            plat_key = a.get("platform", "ALL")
            pos_emoji = POSITIONS.get(pos_key, ("🔄",))[0]
            plat_emoji = PLATFORMS.get(plat_key, ("🌐",))[0]
            lines.append(f"• <@{dc_id}> ({name}) · {pos_emoji} `{pos_key}` · {plat_emoji} `{plat_key}`")

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
