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


async def proces_transferu(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if not database.is_market_open():
        return await interaction.followup.send(
            "⛔ **Rynek transferowy jest obecnie ZAMKNIĘTY!**\n"
            "> Składanie wniosków kontraktowych, transferów i wypożyczeń zostało wstrzymane przez Zarząd Federacji.",
            ephemeral=True
        )
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("❌ Masz już otwarty kanał wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "transfer")
    try:
        await interaction.followup.send(f"Kanał: {kanal.mention}", ephemeral=True)
        embed_start = discord.Embed(
            title="🤝 Wniosek Transferowy",
            description=f"Witaj {user.mention}! Bot poprowadzi Cię przez proces transferu.\n> Masz **15 minut** na każdą odpowiedź.",
            color=0x2b2d31
        )
        embed_start.set_footer(text=f"{league_config.league_name()} • Biuro")
        await kanal.send(embed=embed_start)

        # ── Wybór trybu wniosku ──────────────────────────────────────────────
        tryb_resp = await _zadaj_pytanie(
            kanal, user,
            "**Tryb wniosku:**\n"
            "> `1` · Standardowy transfer / wykup klauzulowy\n"
            "> `2` · Wymiana zawodników (opcjonalna dopłata)",
            client
        )
        jest_wymiana = tryb_resp.strip() == "2"

        # ────────────────────────────────────────────────────────────────────
        if jest_wymiana:
            # ── WYMIANA ZAWODNIKÓW ──────────────────────────────────────────
            while True:
                kup = clean_tag(await _zadaj_pytanie(kanal, user, "Skrót TWOJEGO KLUBU (strona A wymiany):", client))
                if not database.get_club(kup):
                    await kanal.send(embed=discord.Embed(description="❌ Klub nie istnieje!", color=0xe74c3c))
                elif not is_club_board_or_owner(user, kup):
                    await kanal.send(embed=discord.Embed(description="❌ Odmowa – nie jesteś w zarządzie tego klubu!", color=0xe74c3c))
                else:
                    break

            while True:
                sprzed = clean_tag(await _zadaj_pytanie(kanal, user, "Skrót KLUBU DRUGIEJ STRONY (strona B wymiany):", client))
                if not database.get_club(sprzed):
                    await kanal.send(embed=discord.Embed(description="❌ Ten klub nie istnieje!", color=0xe74c3c))
                elif sprzed == kup:
                    await kanal.send(embed=discord.Embed(description="❌ Strony wymiany nie mogą być tym samym klubem!", color=0xe74c3c))
                else:
                    break

            # Zawodnik ze swojego klubu (A → B)
            while True:
                gi_a = await _zadaj_pytanie(kanal, user, f"Zawodnik z TWOJEGO KLUBU `{kup}` do wymiany (oznacz @ lub wpisz imię):", client)
                cn_a, dc_a, lbl_a = await resolve_player_identity(guild, gi_a, client)
                ex_a = database.is_player_under_contract(cn_a, dc_a)
                if not ex_a:
                    await kanal.send(embed=discord.Embed(description=f"❌ `{cn_a}` nie ma aktywnego kontraktu.", color=0xe74c3c)); continue
                if ex_a.get("club_tag", "").upper() != kup:
                    await kanal.send(embed=discord.Embed(description=f"❌ `{cn_a}` nie należy do `{kup}`!", color=0xe74c3c)); continue
                rn_a = clean_player_name(ex_a.get("name")) or cn_a
                if not dc_a and ex_a.get("discord_id"):
                    dc_a = ex_a.get("discord_id")
                    lbl_a = f"**{rn_a}** (<@{dc_a}>)"
                break

            # Zawodnik z drugiego klubu (B → A)
            while True:
                gi_b = await _zadaj_pytanie(kanal, user, f"Zawodnik z KLUBU `{sprzed}` do wymiany (oznacz @ lub wpisz imię):", client)
                cn_b, dc_b, lbl_b = await resolve_player_identity(guild, gi_b, client)
                ex_b = database.is_player_under_contract(cn_b, dc_b)
                if not ex_b:
                    await kanal.send(embed=discord.Embed(description=f"❌ `{cn_b}` nie ma aktywnego kontraktu.", color=0xe74c3c)); continue
                if ex_b.get("club_tag", "").upper() != sprzed:
                    await kanal.send(embed=discord.Embed(description=f"❌ `{cn_b}` nie należy do `{sprzed}`!", color=0xe74c3c)); continue
                rn_b = clean_player_name(ex_b.get("name")) or cn_b
                if not dc_b and ex_b.get("discord_id"):
                    dc_b = ex_b.get("discord_id")
                    lbl_b = f"**{rn_b}** (<@{dc_b}>)"
                break

            # Nowe kontrakty obu zawodników
            while True:
                czas_a = await _zadaj_pytanie(kanal, user, f"Długość kontraktu dla `{rn_a}` w `{sprzed}` (np. `60 dni` lub `31.12.2026`):", client)
                wazny_do_a = parse_expiry_date(czas_a)
                if wazny_do_a: break
                await kanal.send(embed=discord.Embed(description="❌ Błędny format daty.", color=0xe74c3c))

            while True:
                klauz_a = await _zadaj_pytanie(kanal, user, f"Nowa klauzula dla `{rn_a}` (np. `15000`) lub `Brak`:", client)
                if validate_amount_input(klauz_a): break
                await kanal.send(embed=discord.Embed(description="❌ Podaj prawidłową kwotę lub `Brak`.", color=0xe74c3c))

            while True:
                czas_b = await _zadaj_pytanie(kanal, user, f"Długość kontraktu dla `{rn_b}` w `{kup}` (np. `60 dni` lub `31.12.2026`):", client)
                wazny_do_b = parse_expiry_date(czas_b)
                if wazny_do_b: break
                await kanal.send(embed=discord.Embed(description="❌ Błędny format daty.", color=0xe74c3c))

            while True:
                klauz_b = await _zadaj_pytanie(kanal, user, f"Nowa klauzula dla `{rn_b}` (np. `15000`) lub `Brak`:", client)
                if validate_amount_input(klauz_b): break
                await kanal.send(embed=discord.Embed(description="❌ Podaj prawidłową kwotę lub `Brak`.", color=0xe74c3c))

            # Opcjonalne dopłaty
            while True:
                dopl_a = await _zadaj_pytanie(kanal, user, f"Dopłata od `{kup}` (liczba lub `Brak`):", client)
                if validate_amount_input(dopl_a): break
                await kanal.send(embed=discord.Embed(description="❌ Podaj prawidłową kwotę lub `Brak`.", color=0xe74c3c))

            while True:
                dopl_b = await _zadaj_pytanie(kanal, user, f"Dopłata od `{sprzed}` (liczba lub `Brak`):", client)
                if validate_amount_input(dopl_b): break
                await kanal.send(embed=discord.Embed(description="❌ Podaj prawidłową kwotę lub `Brak`.", color=0xe74c3c))

            # Zbuduj embed wymiany
            c_target = database.get_club(kup)
            c_source = database.get_club(sprzed)
            has_target_dc = bool(c_target and (c_target.get("board_ids") or c_target.get("reprezentant_dc")))
            has_source_dc = bool(c_source and (c_source.get("board_ids") or c_source.get("reprezentant_dc")))

            embed = discord.Embed(
                title=f"🔄 Wymiana: {rn_a} ↔ {rn_b}",
                color=0x3498db
            )
            embed.add_field(name="Klub A", value=f"`{kup}`", inline=True)
            embed.add_field(name="Klub B", value=f"`{sprzed}`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
            embed.add_field(name=f"Zawodnik A → B (`{sprzed}`)", value=lbl_a, inline=True)
            embed.add_field(name=f"Zawodnik B → A (`{kup}`)", value=lbl_b, inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
            embed.add_field(name=f"Kontrakt {rn_a} w {sprzed}", value=f"`{wazny_do_a}` | Klauzula: `{klauz_a}`", inline=True)
            embed.add_field(name=f"Kontrakt {rn_b} w {kup}", value=f"`{wazny_do_b}` | Klauzula: `{klauz_b}`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
            embed.add_field(name=f"Dopłata od `{kup}`", value=f"`{dopl_a}`", inline=True)
            embed.add_field(name=f"Dopłata od `{sprzed}`", value=f"`{dopl_b}`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
            embed.add_field(name="Status", value="\n".join([
                f"• `{rn_a}` ({kup}): {'⏳ Oczekuje' if dc_a else 'ℹ️ Brak DC'}",
                f"• `{rn_b}` ({sprzed}): {'⏳ Oczekuje' if dc_b else 'ℹ️ Brak DC'}",
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

            # Kodujemy dane wymiany w polach bazy bez zmiany schematu:
            # amount      = kwota dopłaty od strony A (lub "Brak")
            # new_founder_txt = "WYMIANA|rn_b|dc_b|wazny_do_b|klauz_b|dopl_b"  (zawodnik B)
            # new_board_txt   = "WYMIANA|rn_a|dc_a|wazny_do_a|klauz_a"           (kontrakt zawodnika A)
            wymiana_b_enc = f"WYMIANA|{rn_b}|{dc_b or ''}|{wazny_do_b}|{klauz_b}|{dopl_b}"
            wymiana_a_enc = f"WYMIANA|{rn_a}|{dc_a or ''}|{wazny_do_a}|{klauz_a}"

            app_id = database.create_application(
                app_type="WYMIANA", applicant_id=user.id,
                player_name=rn_a, player_discord_id=dc_a,
                target_club=kup, source_club=sprzed,
                amount=dopl_a,
                clause=klauz_a,
                expires_at=wazny_do_a,
                is_buyout=False,
                needs_player_agree=bool(dc_a or dc_b),
                needs_target_club_agree=has_target_dc,
                needs_source_club_agree=has_source_dc,
                new_founder_txt=wymiana_b_enc,
                new_board_txt=wymiana_a_enc
            )
            thread = await _send_forum_application(guild, kanal, embed,
                                                    f"[{kup}↔{sprzed}] Wymiana: {rn_a} ↔ {rn_b}", app_id,
                                                    ping_target=kup, ping_source=sprzed)
            for dc_id_notify in filter(None, [dc_a, dc_b]):
                await send_dm(client, dc_id_notify,
                              f"🔄 Złożono wniosek o Twoją wymianę między `{kup}` a `{sprzed}`!\n🔗 {thread.jump_url}")

        # ────────────────────────────────────────────────────────────────────
        else:
            # ── STANDARDOWY TRANSFER ────────────────────────────────────────
            while True:
                kup = clean_tag(await _zadaj_pytanie(kanal, user, "Skrót TWOJEGO KLUBU (Kupujący):", client))
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
                sprzed = clean_tag(await _zadaj_pytanie(kanal, user, "Skrót KLUBU SPRZEDAJĄCEGO:", client))
                if not database.get_club(sprzed):
                    await kanal.send(embed=discord.Embed(description="❌ Ten klub nie istnieje!", color=0xe74c3c))
                elif sprzed == kup:
                    await kanal.send(embed=discord.Embed(description="❌ Kupujący i sprzedający nie mogą być identyczni!", color=0xe74c3c))
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
                                        "Aby go pozyskać bez klauzuli, użyj **Podpisania Gracza**.",
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
                kwota = await _zadaj_pytanie(kanal, user, "Kwota transferu (np. `10000`):", client)
                if validate_amount_input(kwota): break
                await kanal.send(embed=discord.Embed(description="❌ Podaj prawidłową kwotę.", color=0xe74c3c))

            while True:
                czas = await _zadaj_pytanie(kanal, user, "Długość nowego kontraktu (np. `60 dni` lub `31.12.2026`):", client)
                wazny_do = parse_expiry_date(czas)
                if wazny_do: break
                await kanal.send(embed=discord.Embed(description="❌ Błędny format daty.", color=0xe74c3c))

            while True:
                klauz = await _zadaj_pytanie(kanal, user, "Nowa Klauzula (np. `15000`) lub `Brak`:", client)
                if validate_amount_input(klauz): break
                await kanal.send(embed=discord.Embed(description="❌ Podaj prawidłową kwotę lub `Brak`.", color=0xe74c3c))

            # Wykup klauzulowy?
            is_buyout = False
            if existing:
                old_clause_val = parse_amount(existing.get("clause", "Brak"))
                kwota_val = parse_amount(kwota)
                if old_clause_val > 0 and kwota_val >= old_clause_val:
                    is_buyout = True

            c_target = database.get_club(kup)
            c_source = database.get_club(sprzed)
            has_target_dc = bool(c_target and (c_target.get("board_ids") or c_target.get("reprezentant_dc")))
            has_source_dc = bool(c_source and (c_source.get("board_ids") or c_source.get("reprezentant_dc")))

            needs_player = bool(player_dc_id)
            needs_target = has_target_dc
            needs_source = (not is_buyout) and has_source_dc

            source_status = "⚡ Zgoda zbędna (wykup klauzulowy)" if is_buyout else \
                ("⏳ Oczekuje" if has_source_dc else "ℹ️ Brak DC zarządu")

            embed = discord.Embed(
                title=f"{'🔥 Wykup Klauzulowy' if is_buyout else '🤝 Transfer'}: {real_name}",
                color=0xe67e22 if is_buyout else 0x9b59b6
            )
            embed.add_field(name="Kupujący", value=f"`{kup}`", inline=True)
            embed.add_field(name="Sprzedający", value=f"`{sprzed}`", inline=True)
            embed.add_field(name="Kwota", value=f"`{kwota}`", inline=True)
            embed.add_field(name="Nowa Klauzula", value=f"`{klauz}`", inline=True)
            embed.add_field(name="Wygasa", value=f"`{wazny_do}`", inline=False)
            embed.add_field(name="Status", value="\n".join([
                f"• Zawodnik: {'⏳ Oczekuje' if needs_player else 'ℹ️ Brak DC'}",
                f"• Klub `{kup}`: {'⏳ Oczekuje' if needs_target else 'ℹ️ Brak DC zarządu'}",
                f"• Klub `{sprzed}`: {source_status}",
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
                app_type="TRANSFER", applicant_id=user.id,
                player_name=real_name, player_discord_id=player_dc_id,
                target_club=kup, source_club=sprzed,
                amount=kwota, clause=klauz, expires_at=wazny_do,
                is_buyout=is_buyout,
                needs_player_agree=needs_player, needs_target_club_agree=needs_target, needs_source_club_agree=needs_source
            )
            thread = await _send_forum_application(guild, kanal, embed,
                                                    f"[{kup}] {'Wykup' if is_buyout else 'Transfer'}: {real_name}", app_id,
                                                    ping_target=kup, ping_source=sprzed)
            if player_dc_id:
                await send_dm(client, player_dc_id,
                              f"📩 Klub `{kup}` złożył wniosek o Twój transfer!\n🔗 {thread.jump_url}")

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_transferu] Błąd: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"❌ Błąd: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await _safe_delete_channel(kanal)
        except Exception: pass


