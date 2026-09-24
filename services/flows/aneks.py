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


async def proces_aneksu(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("❌ Masz już otwarty kanał wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "aneks")
    try:
        await interaction.followup.send(f"Kanał: {kanal.mention}", ephemeral=True)
        embed_start = discord.Embed(
            title="📄 Aneks do Kontraktu",
            description=f"Witaj {user.mention}! Bot poprowadzi Cię przez proces aneksowania umowy.\n> Masz **15 minut** na każdą odpowiedź.",
            color=0x2b2d31
        )
        embed_start.set_footer(text=f"{league_config.league_name()} • Biuro")
        await kanal.send(embed=embed_start)

        # Wybór klubu: Federacja dowolny, właściciel tylko swój
        is_fed = is_federation(user) or (getattr(user, "guild_permissions", None) and user.guild_permissions.administrator)

        while True:
            if is_fed:
                kup_input = await _zadaj_pytanie(kanal, user, "Skrót klubu, dla którego składasz aneks (np. `FCZ`):", client)
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

        # Zawodnik musi być w tym samym klubie
        while True:
            gracz_input = await _zadaj_pytanie(kanal, user, f"Oznacz @Zawodnika z klubu `{user_club}` (lub wpisz imię):", client)
            clean_name, player_dc_id, player_label = await resolve_player_identity(guild, gracz_input, client)
            existing = database.is_player_under_contract(clean_name, player_dc_id)
            if not existing:
                await kanal.send(embed=discord.Embed(description=f"❌ Zawodnik `{clean_name}` nie ma aktywnego kontraktu w bazie!", color=0xe74c3c))
                continue
            if existing.get("club_tag", "").upper() != user_club:
                await kanal.send(embed=discord.Embed(description=f"❌ Zawodnik należy do `{existing.get('club_tag', '?')}`, nie do `{user_club}`!", color=0xe74c3c))
                continue
            real_name = clean_player_name(existing.get("name")) or clean_name
            if not player_dc_id and existing.get("discord_id"):
                player_dc_id = existing.get("discord_id")
                player_label = f"**{real_name}** (<@{player_dc_id}>)"
            break

        stary_termin = existing.get("expires_at", "?")
        stara_klauzula = existing.get("clause", "Brak")
        await kanal.send(f"ℹ️ Obecny kontrakt: termin `{stary_termin}` | klauzula `{stara_klauzula}`")

        while True:
            czas = await _zadaj_pytanie(kanal, user, "Nowy termin kontraktu (np. `90 dni` lub `31.12.2027`):", client)
            wazny_do = parse_expiry_date(czas)
            if wazny_do: break
            await kanal.send(embed=discord.Embed(description="❌ Błędny format daty.", color=0xe74c3c))

        while True:
            klauz = await _zadaj_pytanie(kanal, user, "Nowa Klauzula (np. `10000`) lub `Bez zmian` / `Brak`:", client)
            if validate_amount_input(klauz) or klauz.lower() in ("bez zmian",): break
            await kanal.send(embed=discord.Embed(description="❌ Podaj kwotę (np. `10000`) lub `Bez zmian`.", color=0xe74c3c))

        final_klauz = stara_klauzula if klauz.lower() == "bez zmian" else klauz

        embed = discord.Embed(title=f"📄 Aneks do Kontraktu: {real_name}", color=0x3498db)
        embed.add_field(name="Zawodnik", value=player_label, inline=True)
        embed.add_field(name="Klub", value=f"`{user_club}`", inline=True)
        embed.add_field(name="Stary termin", value=f"`{stary_termin}`", inline=True)
        embed.add_field(name="Nowy termin", value=f"`{wazny_do}`", inline=True)
        embed.add_field(name="Stara klauzula", value=f"`{stara_klauzula}`", inline=True)
        embed.add_field(name="Nowa klauzula", value=f"`{final_klauz}`", inline=True)
        embed.add_field(name="Status", value="\n".join([
            f"• Zawodnik: {'⏳ Oczekuje' if player_dc_id else 'ℹ️ Brak DC'}",
            "• Zarząd Federacji: ⏳ Oczekuje"
        ]), inline=False)
        embed.set_footer(text=f"{league_config.league_name()} • Biuro")

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description="❌ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2); await _safe_delete_channel(kanal); return

        app_id = database.create_application(
            app_type="ANEKS", applicant_id=user.id,
            player_name=real_name, player_discord_id=player_dc_id,
            target_club=user_club, clause=final_klauz, expires_at=wazny_do,
            needs_player_agree=bool(player_dc_id)
        )
        thread = await _send_forum_application(guild, kanal, embed,
                                                f"[ANEKS] {user_club} – {real_name}", app_id, ping_target=user_club)
        if player_dc_id:
            await send_dm(client, player_dc_id,
                          f"📩 Klub `{user_club}` złożył wniosek o aneks do Twojego kontraktu!\n🔗 {thread.jump_url}")

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_aneksu] Błąd: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"❌ Błąd: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await _safe_delete_channel(kanal)
        except Exception: pass


