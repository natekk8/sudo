import discord
from discord import ui

class WniosekConfirmView(ui.View):
    def __init__(self):
        super().__init__(timeout=900.0)
        self.value = None

    @ui.button(label="Zatwierdź i Wyślij", style=discord.ButtonStyle.green, emoji="✅")
    async def btn_confirm(self, interaction: discord.Interaction, button: ui.Button):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @ui.button(label="Anuluj Wniosek", style=discord.ButtonStyle.red, emoji="❌")
    async def btn_cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.value = False
        await interaction.response.defer()
        self.stop()
