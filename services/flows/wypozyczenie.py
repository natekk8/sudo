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


async def proces_wypozyczenia(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if not database.is_market_open():
        return await interaction.followup.send(
            "⛔ **Rynek transferowy jest obecnie ZAMKNIĘTY!**\n"
            "> Składanie wniosków kontraktowych, transferów i wypożyczeń zostało wstrzymane przez Zarząd Federacji.",
            ephemeral=True
        )
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("❌ Masz już otwarty kanał wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "wypozyczenie")
    try:
        await interaction.followup.send(f"Kanał: {kanal.mention}", ephemeral=True)
        embed_start = discord.Embed(
            title="⏱️ Wypożyczenie Zawodnika",
            description=f"Witaj {user.mention}! Bot poprowadzi Cię przez proces wypożyczenia.\n> Masz **15 minut** na każdą odpowiedź.",
            color=0x2b2d31
        )
        embed_start.set_footer(text=f"{league_config.league_name()} • Biuro")
        await kanal.send(embed=embed_start)

        while True:
            kup = clean_tag(await _zadaj_pytanie(kanal, user, "Skrót KLUBU PRZYJMUJĄCEGO (Twojego):", client))
            if not database.get_club(kup):
                await kanal.send(embed=discord.Embed(description="❌ Klub nie istnieje!", color=0xe74c3c))
            elif not is_club_board_or_owner(user, kup):
                await kanal.send(embed=discord.Embed(description="❌ Odmowa – nie jesteś w zarządzie tego klubu!", color=0xe74c3c))
            elif database.get_club_player_count(kup) > league_config.max_players():
                await kanal.send(embed=discord.Embed(description=f"❌ Klub osiągnął bezwzględny limit ({league_config.max_players()+1}/{league_config.max_players()}).", color=0xe74c3c))
                await asyncio.sleep(5); await _safe_delete_channel(kanal); return
            else:
                break

        while True:
            sprzed = clean_tag(await _zadaj_pytanie(kanal, user, "Skrót KLUBU ODDAJĄCEGO:", client))
            if not database.get_club(sprzed):
                await kanal.send(embed=discord.Embed(description="❌ Ten klub nie istnieje!", color=0xe74c3c))
            elif sprzed == kup:
                await kanal.send(embed=discord.Embed(description="❌ Przyjmujący i oddający nie mogą być identyczni!", color=0xe74c3c))
            else:
                break

        while True:
            gracz_input = await _zadaj_pytanie(kanal, user, "Oznacz @Zawodnika (lub wpisz imię jeśli brak DC):", client)
            clean_name, player_dc_id, player_label = await resolve_player_identity(guild, gracz_input, client)

            existing = database.is_player_under_contract(clean_name, player_dc_id)
            if not existing:
                await kanal.send(
                    embed=discord.Embed(
                        description=f"❌ **Zawodnik `{clean_name}` nie posiada aktywnego kontraktu!**\n"
                                    "Aby go pozyskać, użyj **Podpisania Gracza**.",
                        color=0xe74c3c
                    )
                )
                continue
            if existing.get("club_tag", "").upper() != sprzed:
                actual = existing.get("club_tag", "?")
                await kanal.send(embed=discord.Embed(description=f"❌ Zawodnik należy do `{actual}`, a nie `{sprzed}`!", color=0xe74c3c))
                continue
            real_name = clean_player_name(existing.get("name")) or clean_name
            if not player_dc_id and existing.get("discord_id"):
                player_dc_id = existing.get("discord_id")
                player_label = f"**{real_name}** (<@{player_dc_id}>)"
            break

        while True:
            czas = await _zadaj_pytanie(kanal, user, "Okres wypożyczenia (np. `30 dni` lub `15.01.2027`):", client)
            wazny_do = parse_expiry_date(czas)
            if wazny_do: break
            await kanal.send(embed=discord.Embed(description="❌ Błędny format daty.", color=0xe74c3c))

        while True:
            kwota = await _zadaj_pytanie(kanal, user, "Opłata za wypożyczenie (np. `2000`) lub `Brak`:", client)
            if validate_amount_input(kwota): break
            await kanal.send(embed=discord.Embed(description="❌ Podaj prawidłową kwotę lub `Brak`.", color=0xe74c3c))

        c_target = database.get_club(kup)
        c_source = database.get_club(sprzed)
        has_target_dc = bool(c_target and (c_target.get("board_ids") or c_target.get("reprezentant_dc")))
        has_source_dc = bool(c_source and (c_source.get("board_ids") or c_source.get("reprezentant_dc")))

        embed = discord.Embed(title=f"⏱️ Wypożyczenie: {real_name}", color=0x1abc9c)
        embed.add_field(name="Przyjmujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Oddający", value=f"`{sprzed}`", inline=True)
        embed.add_field(name="Opłata", value=f"`{kwota}`", inline=True)
        embed.add_field(name="Koniec wypożyczenia", value=f"`{wazny_do}`", inline=False)
        embed.add_field(name="Status", value="\n".join([
            f"• Zawodnik: {'⏳ Oczekuje' if player_dc_id else 'ℹ️ Brak DC'}",
            f"• Klub `{kup}`: {'⏳ Oczekuje' if has_target_dc else 'ℹ️ Brak DC zarządu'}",
            f"• Klub `{sprzed}`: {'⏳ Oczekuje' if has_source_dc else 'ℹ️ Brak DC zarządu'}",
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
            app_type="WYPOZYCZENIE", applicant_id=user.id,
            player_name=real_name, player_discord_id=player_dc_id,
            target_club=kup, source_club=sprzed,
            amount=kwota, clause="Bez zmian", expires_at=wazny_do,
            needs_player_agree=bool(player_dc_id),
            needs_target_club_agree=has_target_dc, needs_source_club_agree=has_source_dc
        )
        thread = await _send_forum_application(guild, kanal, embed,
                                                f"[{kup}] Wypożyczenie: {real_name}", app_id,
                                                ping_target=kup, ping_source=sprzed)
        if player_dc_id:
            await send_dm(client, player_dc_id,
                          f"📩 Klub `{kup}` złożył wniosek o Twoje wypożyczenie!\n🔗 {thread.jump_url}")

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_wypozyczenia] Błąd: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"❌ Błąd: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await _safe_delete_channel(kanal)
        except Exception: pass


