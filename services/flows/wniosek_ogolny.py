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


async def proces_wniosku_ogolnego(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("❌ Masz już otwarty kanał wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "wniosek")
    try:
        await interaction.followup.send(f"Kanał: {kanal.mention}", ephemeral=True)
        embed_start = discord.Embed(
            title="📨 Wniosek Ogólny do Zarządu Federacji",
            description=(
                f"Witaj {user.mention}! Skorzystaj z tego formularza, aby zgłosić sprawę do Zarządu Federacji Siatkówki Stołowej.\n"
                "> Przykłady: przełożenie meczu, reklamacja, zapytanie regulaminowe, inne.\n"
                "> Masz **15 minut** na każdą odpowiedź."
            ),
            color=0x2b2d31
        )
        embed_start.set_footer(text=f"{league_config.league_name()} • Biuro")
        await kanal.send(embed=embed_start)

        temat = await _zadaj_pytanie(kanal, user, "Temat wniosku (np. `Przełożenie meczu`, `Reklamacja decyzji`):", client)

        while True:
            klub_input = await _zadaj_pytanie(kanal, user, "Skrót klubu, którego dotyczy wniosek (lub `Brak`):", client)
            if klub_input.strip().lower() == "brak":
                klub_tag = None
                break
            klub_tag = clean_tag(klub_input)
            if database.get_club(klub_tag) or klub_tag == "BRAK":
                if klub_tag == "BRAK": klub_tag = None
                break
            await kanal.send(embed=discord.Embed(description=f"❌ Klub `{klub_tag}` nie istnieje. Wpisz poprawny TAG lub `Brak`.", color=0xe74c3c))

        tresc = await _zadaj_pytanie(kanal, user, "Opisz szczegółowo treść wniosku:", client)

        embed = discord.Embed(
            title=f"📨 Wniosek: {temat[:50]}",
            description=tresc,
            color=0x5865f2
        )
        embed.add_field(name="Wnioskodawca", value=user.mention, inline=True)
        if klub_tag:
            embed.add_field(name="Klub", value=f"`{klub_tag}`", inline=True)
        embed.add_field(name="Status", value="⏳ Oczekuje na decyzję Zarządu Federacji", inline=False)
        embed.set_footer(text=f"{league_config.league_name()} • Biuro")

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description="❌ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2); await _safe_delete_channel(kanal); return

        app_id = database.create_application(
            app_type="WNIOSEK_OGOLNY", applicant_id=user.id,
            club_tag=klub_tag, reason=temat,
            new_board_txt=tresc  # przechowujemy treść w wolnym polu tekstowym
        )
        await _send_forum_application(guild, kanal, embed,
                                       f"[WNIOSEK] {temat[:40]}", app_id)

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_wniosku_ogolnego] Błąd: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"❌ Błąd: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await _safe_delete_channel(kanal)
        except Exception: pass

