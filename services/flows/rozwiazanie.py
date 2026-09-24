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


async def proces_rozwiazania(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("❌ Masz już otwarty kanał wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "rozwiazanie")
    try:
        await interaction.followup.send(f"Kanał: {kanal.mention}", ephemeral=True)
        embed_start = discord.Embed(
            title="❌ Rozwiązanie Kontraktu",
            description=f"Witaj {user.mention}! Bot poprowadzi Cię przez proces rozwiązania umowy.\n> Masz **15 minut** na każdą odpowiedź.",
            color=0x2b2d31
        )
        embed_start.set_footer(text=f"{league_config.league_name()} • Biuro")
        await kanal.send(embed=embed_start)

        is_fed = is_federation(user) or (getattr(user, "guild_permissions", None) and user.guild_permissions.administrator)

        while True:
            if is_fed:
                kup_input = await _zadaj_pytanie(kanal, user, "Skrót klubu, dla którego składasz wniosek o rozwiązanie (np. `FCZ`):", client)
            else:
                kup_input = await _zadaj_pytanie(kanal, user, "Podaj skrót SWOJEGO KLUBU (np. `FCZ`):", client)
            user_club = clean_tag(kup_input)
            if not database.get_club(user_club):
                await kanal.send(embed=discord.Embed(description=f"❌ Klub `{user_club}` nie istnieje!", color=0xe74c3c))
                continue
            if not is_club_board_or_owner(user, user_club):
                await kanal.send(embed=discord.Embed(description="❌ Nie jesteś w zarządzie tego klubu!", color=0xe74c3c))
                continue
            break

        # Usunięto tryb dyscyplinarny - wymuszamy tryb polubowny
        tryb = "1"
        is_disciplinary = False

        while True:
            kup = clean_tag(await _zadaj_pytanie(kanal, user, "Podaj skrót TWOJEGO KLUBU:", client))
            if not database.get_club(kup):
                await kanal.send(embed=discord.Embed(description="❌ Klub nie istnieje!", color=0xe74c3c))
            elif not is_club_board_or_owner(user, kup):
                await kanal.send(embed=discord.Embed(description="❌ Nie jesteś w zarządzie tego klubu!", color=0xe74c3c))
            else:
                break

        while True:
            gracz_input = await _zadaj_pytanie(kanal, user, f"Oznacz @Zawodnika do rozwiązania (z klubu `{user_club}`):", client)
            clean_name, player_dc_id, player_label = await resolve_player_identity(guild, gracz_input, client)
            existing = database.is_player_under_contract(clean_name, player_dc_id)
            if not existing:
                await kanal.send(embed=discord.Embed(description=f"❌ Zawodnik `{clean_name}` nie istnieje w bazie!", color=0xe74c3c))
                continue
            if existing.get("club_tag", "").upper() != user_club:
                await kanal.send(embed=discord.Embed(description=f"❌ Zawodnik należy do `{existing.get('club_tag', '?')}`, nie do `{user_club}`!", color=0xe74c3c))
                continue
            real_name = clean_player_name(existing.get("name")) or clean_name
            if not player_dc_id and existing.get("discord_id"):
                player_dc_id = existing.get("discord_id")
                player_label = f"**{real_name}** (<@{player_dc_id}>)"
            break

        uzasadnienie = await _zadaj_pytanie(kanal, user, "Podaj krótkie uzasadnienie rozwiązania:", client)

        app_type = "ROZWIAZANIE_POLUBOWNE"
        needs_player = bool(player_dc_id)

        embed = discord.Embed(
            title=f"🤝 Porozumienie stron: {real_name}",
            color=0xe67e22
        )
        embed.add_field(name="Zawodnik", value=player_label, inline=True)
        embed.add_field(name="Klub", value=f"`{user_club}`", inline=True)
        embed.add_field(name="Tryb", value="Za porozumieniem stron", inline=True)
        embed.add_field(name="Uzasadnienie", value=uzasadnienie, inline=False)
        embed.add_field(name="Status", value="\n".join([
            f"• Zawodnik: {'⏳ Oczekuje zgody' if needs_player else ('ℹ️ Brak DC' if not player_dc_id else '🔔 Będzie powiadomiony')}",
            "• Zarząd Federacji: ⏳ Oczekuje na ostateczną decyzję"
        ]), inline=False)
        embed.set_footer(text=f"{league_config.league_name()} • Biuro")

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description="❌ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2); await _safe_delete_channel(kanal); return

        app_id = database.create_application(
            app_type=app_type, applicant_id=user.id,
            player_name=real_name, player_discord_id=player_dc_id,
            source_club=user_club, reason=uzasadnienie,
            needs_player_agree=needs_player
        )
        thread = await _send_forum_application(guild, kanal, embed,
                                                f"[ROZWIĄZANIE] {user_club} – {real_name}", app_id)
        if player_dc_id:
            msg = f"📩 Klub `{user_club}` złożył wniosek o rozwiązanie kontraktu za porozumieniem stron.\n🔗 {thread.jump_url}"
            await send_dm(client, player_dc_id, msg)

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_rozwiazania] Błąd: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"❌ Błąd: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await _safe_delete_channel(kanal)
        except Exception: pass


