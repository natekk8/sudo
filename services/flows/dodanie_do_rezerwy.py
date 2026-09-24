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


async def proces_dodania_do_rezerwy(interaction: discord.Interaction, client):
    guild, user = interaction.guild, interaction.user
    if _check_spam(guild, user, interaction):
        return await interaction.response.send_message("❌ Masz już otwarty kanał wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "rezerwa")
    try:
        await interaction.response.send_message(f"Kanał: {kanal.mention}", ephemeral=True)
        embed_start = discord.Embed(
            title="🙋 Dodanie zawodnika do Bazy Rezerwowej",
            description=f"Witaj {user.mention}! Możesz tutaj dodać zawodnika na giełdę wolnych agentów (Baza Rezerwowa).\n> Masz **15 minut** na każdą odpowiedź.",
            color=0x2b2d31
        )
        embed_start.set_footer(text=f"{league_config.league_name()} • Biuro")
        await kanal.send(embed=embed_start)

        gracz_input = await _zadaj_pytanie(kanal, user, "Oznacz @Zawodnika (lub podaj Imię i Nazwisko, jeśli nie ma DC):", client)
        clean_name, player_dc_id, player_label = await resolve_player_identity(guild, gracz_input, client)

        if player_dc_id:
            existing = database.get_player_by_discord_id(player_dc_id)
            if existing and existing.get("club_tag"):
                await kanal.send(embed=discord.Embed(description=f"❌ Zawodnik jest już w klubie `{existing['club_tag']}`!", color=0xe74c3c))
                await asyncio.sleep(5); await _safe_delete_channel(kanal); return
            if database.is_free_agent(player_dc_id):
                await kanal.send(embed=discord.Embed(description="❌ Ten zawodnik jest już na liście Bazy Rezerwowej!", color=0xe74c3c))
                await asyncio.sleep(5); await _safe_delete_channel(kanal); return

        embed = discord.Embed(
            title="🙋 Baza Rezerwowa: Potwierdzenie",
            description=f"Chcesz dodać {player_label} do Bazy Rezerwowej (Wolnych Agentów).",
            color=0x2ecc71
        )
        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description="❌ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2); await _safe_delete_channel(kanal); return

        if player_dc_id:
            database.register_free_agent(player_dc_id, clean_name)
        
        await kanal.send(embed=discord.Embed(description=f"✅ Pomyślnie dodano zawodnika {player_label} do Bazy Rezerwowej.", color=0x2ecc71))
        
        kom_channel = await get_komunikaty_channel(client, guild)
        if kom_channel:
            await kom_channel.send(f"📢 Zawodnik **{player_label}** dołączył do **Bazy Rezerwowej** i poszukuje klubu!", allowed_mentions=discord.AllowedMentions.none())
            
        await asyncio.sleep(3); await _safe_delete_channel(kanal)

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_dodania_do_rezerwy] Błąd: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"❌ Błąd: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await _safe_delete_channel(kanal)
        except Exception: pass

