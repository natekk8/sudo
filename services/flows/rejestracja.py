import asyncio
import traceback
import discord
from discord import ui
import database
import utils.league_config as league_config
from utils.helpers import *
from views.confirmation import WniosekConfirmView
from views.application_view import ForumApplicationView
from .shared import _create_ticket_channel, _safe_delete_channel, _zadaj_pytanie, _send_forum_application, _check_spam


async def proces_rejestracji_klubu(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("❌ Masz już otwarty kanał wniosku. Dokończ go lub poczekaj.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "rejestracja")
    try:
        await interaction.followup.send(f"Kanał: {kanal.mention}", ephemeral=True)
        embed_start = discord.Embed(
            title="🏛️ Rejestracja Nowego Klubu",
            description=f"Witaj {user.mention}! Bot poprowadzi Cię przez proces rejestracji.\n> Masz **15 minut** na każdą odpowiedź.",
            color=0x2b2d31
        )
        embed_start.set_footer(text=f"{league_config.league_name()} • Biuro")
        await kanal.send(embed=embed_start)

        nazwa = await _zadaj_pytanie(kanal, user, "Podaj pełną nazwę drużyny (np. FC Łazy):", client)

        while True:
            skrot = clean_tag(await _zadaj_pytanie(kanal, user, "Podaj skrót (dokładnie **3 litery/cyfry**, np. LAZ):", client))
            if not is_valid_tag(skrot):
                await kanal.send(embed=discord.Embed(description="❌ Skrót musi składać się dokładnie z 3 liter lub cyfr (A-Z, 0-9)!", color=0xe74c3c))
            elif database.get_club(skrot):
                await kanal.send(embed=discord.Embed(description=f"❌ Skrót `{skrot}` jest już zajęty!", color=0xe74c3c))
            else:
                break

        wlasciciel = await _zadaj_pytanie(kanal, user, "Oznacz @Właściciela Klubu (lub wpisz imię jeśli brak DC):", client)
        zarzad = await _zadaj_pytanie(kanal, user, "Oznacz @Pozostały Zarząd (lub wpisz 'Brak'):", client)

        embed = discord.Embed(title=f"🏛️ Podsumowanie: {nazwa}", color=0x2b2d31)
        embed.add_field(name="Skrót", value=f"`{skrot}`", inline=True)
        embed.add_field(name="Właściciel", value=wlasciciel, inline=True)
        embed.add_field(name="Zarząd", value=zarzad, inline=False)
        embed.add_field(name="Status", value="⏳ Oczekuje na decyzję Zarządu Federacji", inline=False)

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description="❌ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2)
            await _safe_delete_channel(kanal)
            return

        app_id = database.create_application(
            app_type="REJESTRACJA_KLUBU", applicant_id=user.id,
            club_name=nazwa, club_tag=skrot, founder_txt=wlasciciel, board_txt=zarzad
        )
        await _send_forum_application(guild, kanal, embed, f"[{skrot}] Rejestracja: {nazwa}", app_id)

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_rejestracji_klubu] Błąd: {e}\n{traceback.format_exc()}")
        try:
            await kanal.send(embed=discord.Embed(description=f"❌ Błąd: `{e}`", color=0xe74c3c))
            await asyncio.sleep(5)
            await _safe_delete_channel(kanal)
        except Exception:
            pass


