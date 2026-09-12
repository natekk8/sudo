import discord
from discord import ui

class WniosekConfirmView(ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=900.0)
        self.value = None
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Tylko autor wniosku może użyć tych przycisków.", ephemeral=True
            )
            return False
        return True

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
