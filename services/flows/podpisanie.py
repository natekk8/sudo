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


async def proces_podpisania(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if not database.is_market_open():
        return await interaction.followup.send(
            "⛔ **Rynek transferowy jest obecnie ZAMKNIĘTY!**\n"
            "> Składanie wniosków kontraktowych, transferów i wypożyczeń zostało wstrzymane przez Zarząd Federacji.",
            ephemeral=True
        )
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("❌ Masz już otwarty kanał wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "kontrakt")
    try:
        await interaction.followup.send(f"Kanał: {kanal.mention}", ephemeral=True)
        embed_start = discord.Embed(
            title="👤 Podpisanie Nowego Gracza",
            description=f"Witaj {user.mention}! Bot poprowadzi Cię przez proces podpisania zawodnika.\n> Masz **15 minut** na każdą odpowiedź.",
            color=0x2b2d31
        )
        embed_start.set_footer(text=f"{league_config.league_name()} • Biuro")
        await kanal.send(embed=embed_start)

        while True:
            kup = clean_tag(await _zadaj_pytanie(kanal, user, "Podaj skrót TWOJEGO KLUBU (kupującego):", client))
            if not database.get_club(kup):
                await kanal.send(embed=discord.Embed(description="❌ Klub nie istnieje!", color=0xe74c3c))
            elif not is_club_board_or_owner(user, kup):
                await kanal.send(embed=discord.Embed(description="❌ Nie jesteś w zarządzie tego klubu!", color=0xe74c3c))
            elif database.get_club_player_count(kup) > league_config.max_players():
                await kanal.send(embed=discord.Embed(description=f"❌ Klub osiągnął bezwzględny limit ({league_config.max_players()+1}/{league_config.max_players()}).", color=0xe74c3c))
                await asyncio.sleep(5)
                await _safe_delete_channel(kanal)
                return
            else:
                break

        gracz_input = await _zadaj_pytanie(kanal, user, "Oznacz @Zawodnika (lub wpisz imię jeśli brak DC):", client)
        clean_name, player_dc_id, player_label = await resolve_player_identity(guild, gracz_input, client)

        # Blokada kradzieży: zawodnik nie może już mieć kontraktu
        existing = database.is_player_under_contract(clean_name, player_dc_id)
        if existing:
            await kanal.send(
                embed=discord.Embed(
                    description=f"❌ **Zawodnik `{player_label}` ma już aktywny kontrakt z `{existing.get('club_tag', '?')}`!**\n"
                                "Użyj **Wniosku Transferowego** zamiast Podpisania Gracza.",
                    color=0xe74c3c
                )
            )
            await asyncio.sleep(5)
            await _safe_delete_channel(kanal)
            return

        while True:
            czas = await _zadaj_pytanie(kanal, user, "Długość kontraktu (np. `30`, `30 dni`, `30.06.2027`):", client)
            wazny_do = parse_expiry_date(czas)
            if wazny_do: break
            await kanal.send(embed=discord.Embed(description="❌ Błędny format. Wpisz liczbę dni (np. `14`) lub datę `DD.MM.RRRR`.", color=0xe74c3c))

        while True:
            klauz = await _zadaj_pytanie(kanal, user, "Kwota Klauzuli (np. `5000`) lub `Brak`:", client)
            if validate_amount_input(klauz): break
            await kanal.send(embed=discord.Embed(description="❌ Podaj prawidłową kwotę (np. `5000`) lub `Brak`.", color=0xe74c3c))

        c_target = database.get_club(kup)
        has_target_dc = bool(c_target and (c_target.get("board_ids") or c_target.get("reprezentant_dc")))
        needs_player = bool(player_dc_id)
        needs_target = has_target_dc

        embed = discord.Embed(title=f"📄 Podpisanie Gracza: {clean_name}", color=0x3498db)
        embed.add_field(name="Zawodnik", value=player_label, inline=True)
        embed.add_field(name="Kupujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Wygasa", value=f"`{wazny_do}`", inline=True)
        embed.add_field(name="Klauzula", value=f"`{klauz}`", inline=True)
        embed.add_field(name="Status", value="\n".join([
            f"• Zawodnik: {'⏳ Oczekuje' if needs_player else 'ℹ️ Brak DC'}",
            f"• Klub `{kup}`: {'⏳ Oczekuje' if needs_target else 'ℹ️ Brak DC zarządu'}",
            "• Zarząd Federacji: ⏳ Oczekuje"
        ]), inline=False)
        embed.set_footer(text=f"{league_config.league_name()} • Biuro")

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description="❌ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2)
            await _safe_delete_channel(kanal)
            return

        app_id = database.create_application(
            app_type="PODPISANIE", applicant_id=user.id,
            player_name=clean_name, player_discord_id=player_dc_id,
            target_club=kup, clause=klauz, expires_at=wazny_do,
            needs_player_agree=needs_player, needs_target_club_agree=needs_target
        )
        thread = await _send_forum_application(guild, kanal, embed, f"[{kup}] Nowy Gracz: {clean_name}", app_id, ping_target=kup)
        if player_dc_id:
            await send_dm(client, player_dc_id,
                          f"📩 Klub `{kup}` złożył wniosek o Twoje podpisanie w Federacji Siatkówki Stołowej (FSS)!\n🔗 {thread.jump_url}")

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_podpisania] Błąd: {e}\n{traceback.format_exc()}")
        try:
            await kanal.send(embed=discord.Embed(description=f"❌ Błąd: `{e}`", color=0xe74c3c))
            await asyncio.sleep(5)
            await _safe_delete_channel(kanal)
        except Exception:
            pass


