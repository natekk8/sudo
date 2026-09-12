import discord
from discord import ui
from config import MAX_PLAYERS_PER_CLUB

class WidokPaneluGlownego(ui.View):
    """Panel Biuro Federacji – operacje formalne (Wiadomość 1)."""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Rejestracja Klubu", style=discord.ButtonStyle.primary,
               emoji="📝", custom_id="p_klub")
    async def b_klub(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from services.ticket_flows import proces_rejestracji_klubu
        interaction.client.loop.create_task(proces_rejestracji_klubu(interaction))

    @ui.button(label="Podpisanie gracza", style=discord.ButtonStyle.success,
               emoji="👤", custom_id="p_wolny")
    async def b_wolny(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from services.ticket_flows import proces_podpisania
        interaction.client.loop.create_task(proces_podpisania(interaction))

    @ui.button(label="Wniosek Transferowy", style=discord.ButtonStyle.secondary,
               emoji="🤝", custom_id="p_trans")
    async def b_trans(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from services.ticket_flows import proces_transferu
        interaction.client.loop.create_task(proces_transferu(interaction))

    @ui.button(label="Wypożyczenie", style=discord.ButtonStyle.secondary,
               emoji="⏱️", custom_id="p_wyp")
    async def b_wyp(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from services.ticket_flows import proces_wypozyczenia
        interaction.client.loop.create_task(proces_wypozyczenia(interaction))
