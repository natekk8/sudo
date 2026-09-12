import discord
from discord import ui
from config import MAX_PLAYERS_PER_CLUB

class WidokPaneluGlownego(ui.View):
    """Panel Biuro Federacji – oficjalne operacje ligowe (Wiadomość 1)."""

    def __init__(self):
        super().__init__(timeout=None)

    # ── Rząd 1: Podstawowe wnioski ──

    @ui.button(label="Rejestracja Klubu", style=discord.ButtonStyle.primary,
               emoji="📝", custom_id="p_klub", row=0)
    async def b_klub(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from services.ticket_flows import proces_rejestracji_klubu
        interaction.client.loop.create_task(proces_rejestracji_klubu(interaction))

    @ui.button(label="Podpisanie Gracza", style=discord.ButtonStyle.success,
               emoji="👤", custom_id="p_wolny", row=0)
    async def b_wolny(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from services.ticket_flows import proces_podpisania
        interaction.client.loop.create_task(proces_podpisania(interaction))

    @ui.button(label="Wniosek Transferowy", style=discord.ButtonStyle.secondary,
               emoji="🤝", custom_id="p_trans", row=0)
    async def b_trans(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from services.ticket_flows import proces_transferu
        interaction.client.loop.create_task(proces_transferu(interaction))

    @ui.button(label="Wypożyczenie", style=discord.ButtonStyle.secondary,
               emoji="⏱️", custom_id="p_wyp", row=0)
    async def b_wyp(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from services.ticket_flows import proces_wypozyczenia
        interaction.client.loop.create_task(proces_wypozyczenia(interaction))

    # ── Rząd 2: Zarządzanie kontraktami i klubami ──

    @ui.button(label="Aneks do Umowy", style=discord.ButtonStyle.primary,
               emoji="📄", custom_id="p_aneks", row=1)
    async def b_aneks(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from services.ticket_flows import proces_aneksu
        interaction.client.loop.create_task(proces_aneksu(interaction))

    @ui.button(label="Rozwiązanie Umowy", style=discord.ButtonStyle.danger,
               emoji="❌", custom_id="p_rozw", row=1)
    async def b_rozw(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from services.ticket_flows import proces_rozwiazania
        interaction.client.loop.create_task(proces_rozwiazania(interaction))

    @ui.button(label="Rebranding Klubu", style=discord.ButtonStyle.secondary,
               emoji="🔄", custom_id="p_rebrand", row=1)
    async def b_rebrand(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from services.ticket_flows import proces_rebrandingu
        interaction.client.loop.create_task(proces_rebrandingu(interaction))
