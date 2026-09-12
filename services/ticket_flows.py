import asyncio
import traceback
import discord
from discord import ui
import database
from config import ROLE_FEDERACJA_ID, CHANNEL_FORUM_ID, MAX_PLAYERS_PER_CLUB
from utils.helpers import clean_tag, extract_ids, parse_expiry_date, parse_amount, is_club_board_or_owner, ping_representatives
from views.confirmation import WniosekConfirmView
from views.application_view import ForumApplicationView

async def utworz_kanal_ticket(interaction: discord.Interaction, prefix: str) -> discord.TextChannel:
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }

    rola_fed = guild.get_role(ROLE_FEDERACJA_ID)
    if rola_fed:
        overwrites[rola_fed] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    ticket_id = database.get_next_ticket_id()
    nazwa_kanalu = f"{prefix}-{ticket_id}"
    kanal = await guild.create_text_channel(nazwa_kanalu, overwrites=overwrites)
    await interaction.followup.send(f"Utworzono kanał wniosku: {kanal.mention}", ephemeral=True)
    return kanal

async def zadaj_pytanie(kanal: discord.TextChannel, uzytkownik: discord.Member, pytanie: str, client: discord.Client) -> str:
    await kanal.send(f"🤖 **[Pytanie]** {pytanie}")
    def check(m):
        return m.author == uzytkownik and m.channel == kanal

    try:
        msg = await client.wait_for('message', check=check, timeout=900.0)
        return msg.content.strip()
    except asyncio.TimeoutError:
        await kanal.send("⏳ **Minęło 15 minut braku aktywności.** Wniosek został anulowany, usuwam kanał...")
        await asyncio.sleep(3)
        await kanal.delete()
        raise TimeoutError("Timeout ankiety ticketu")

# =========================================================================
# 1. PROCES REJESTRACJI KLUBU
# =========================================================================
async def proces_rejestracji_klubu(interaction: discord.Interaction):
    kanal = await utworz_kanal_ticket(interaction, "rejestracja")
    client = interaction.client
    try:
        await kanal.send(f"Witaj {interaction.user.mention}! Rozpoczynamy rejestrację klubu.\n*Masz 15 minut na każdą odpowiedź.*")
        nazwa = await zadaj_pytanie(kanal, interaction.user, "Podaj pełną nazwę drużyny (np. FC Łazy):", client)

        while True:
            skrot = await zadaj_pytanie(kanal, interaction.user, "Podaj skrót drużyny (Dokładnie 3 litery, np. LAZ):", client)
            skrot = clean_tag(skrot)
            if len(skrot) != 3:
                await kanal.send("❌ Skrót musi mieć dokładnie 3 litery!")
            elif database.get_club(skrot):
                await kanal.send(f"❌ Skrót `{skrot}` jest już zajęty!")
            else:
                break

        zalozyciel = await zadaj_pytanie(kanal, interaction.user, "Oznacz @Głównego Założyciela (lub wpisz Imię jeśli nie ma DC):", client)
        zarzad = await zadaj_pytanie(kanal, interaction.user, "Oznacz @Pozostały Zarząd (lub wpisz 'Brak'):", client)

        embed = discord.Embed(title=f"🏛️ Podsumowanie: {nazwa}", color=0x2b2d31)
        embed.add_field(name="Skrót", value=skrot, inline=True)
        embed.add_field(name="Założyciel", value=zalozyciel, inline=True)
        embed.add_field(name="Zarząd", value=zarzad, inline=False)
        embed.add_field(name="Status", value="⏳ Oczekuje na decyzję Zarządu Federacji", inline=False)

        view = WniosekConfirmView()
        await kanal.send(embed=embed, view=view)
        await view.wait()

        if view.value is None:
            await kanal.send("⏳ **Minęło 15 minut bez potwierdzenia.** Zamykam kanał...")
            await asyncio.sleep(3)
            await kanal.delete()
            return

        if view.value:
            app_id = database.create_application(
                app_type="REJESTRACJA_KLUBU",
                applicant_id=interaction.user.id,
                club_name=nazwa,
                club_tag=skrot,
                founder_txt=zalozyciel,
                board_txt=zarzad
            )

            forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
            v_forum = ForumApplicationView(app_id)
            thread = await forum.create_thread(name=f"[{skrot}] {nazwa}", embed=embed, view=v_forum)
            database.set_application_message(app_id, thread.thread.id, thread.message.id)

            await kanal.send(f"✅ Wysłano! {thread.thread.mention}. Zamykam kanał...")

        await asyncio.sleep(2)
        await kanal.delete()
    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_rejestracji_klubu] Błąd: {e}\n{traceback.format_exc()}")
        try:
            await kanal.send(f"❌ Wystąpił błąd podczas rejestracji: {e}")
            await asyncio.sleep(5)
            await kanal.delete()
        except Exception:
            pass

# =========================================================================
# 2. PROCES PODPISANIA GRACZA (BEZ KLUBU)
# =========================================================================
async def proces_podpisania(interaction: discord.Interaction):
    kanal = await utworz_kanal_ticket(interaction, "kontrakt")
    client = interaction.client
    try:
        await kanal.send(f"*Masz 15 minut na każdą odpowiedź.*")
        while True:
            kup = await zadaj_pytanie(kanal, interaction.user, "Podaj skrót TWOJEGO KLUBU (kupującego):", client)
            kup = clean_tag(kup)
            if not is_club_board_or_owner(interaction.user, kup):
                await kanal.send("❌ Nie jesteś w zarządzie tego klubu lub klub nie istnieje w bazie!")
                continue

            current_count = database.get_club_player_count(kup)
            if current_count >= MAX_PLAYERS_PER_CLUB:
                await kanal.send(f"❌ Twój klub posiada już maksymalną dopuszczalną liczbę zawodników ({current_count}/{MAX_PLAYERS_PER_CLUB})! Rejestracja kolejnego gracza jest niemożliwa.")
                await asyncio.sleep(5)
                await kanal.delete()
                return
            break

        gracz = await zadaj_pytanie(kanal, interaction.user, "Oznacz @Zawodnika (lub wpisz jego imię jeśli nie ma DC):", client)
        extracted_gracz = extract_ids(gracz)
        player_discord_id = extracted_gracz[0] if extracted_gracz else None

        while True:
            czas_input = await zadaj_pytanie(kanal, interaction.user, "Podaj długość kontraktu (np. '30' lub '30 dni', albo datę '30.06.2027'):", client)
            wazny_do = parse_expiry_date(czas_input)
            if wazny_do: break
            await kanal.send("❌ Nieprawidłowy format! Wpisz liczbę dni (np. 14) lub przyszłą datę DD.MM.RRRR.")

        klauz = await zadaj_pytanie(kanal, interaction.user, "Podaj kwotę Klauzuli (lub wpisz 'Brak'):", client)

        c_target = database.get_club(kup)
        has_target_board_dc = bool(c_target and (c_target.get("board_ids") or c_target.get("reprezentant_dc")))
        needs_player = bool(player_discord_id)
        needs_target = has_target_board_dc

        embed = discord.Embed(title=f"📄 Podpisanie Gracza: {gracz}", color=0x3498db)
        embed.add_field(name="Kupujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Wygasa", value=f"`{wazny_do}`", inline=True)
        embed.add_field(name="Klauzula", value=klauz, inline=True)

        status_text = (
            f"• Zawodnik: {'⏳ Oczekuje' if needs_player else 'ℹ️ Brak konta Discord (kontakt poza DC)'}\n"
            f"• Klub `{kup}`: {'⏳ Oczekuje' if needs_target else 'ℹ️ Brak oznaczonych kont zarządu'}\n"
            "• Zarząd Federacji: ⏳ Oczekuje na decyzję"
        )
        embed.add_field(name="Status", value=status_text, inline=False)

        view = WniosekConfirmView()
        await kanal.send(embed=embed, view=view)
        await view.wait()

        if view.value is None:
            await kanal.send("⏳ **Minęło 15 minut bez potwierdzenia.** Zamykam kanał...")
            await asyncio.sleep(3)
            await kanal.delete()
            return

        if view.value:
            app_id = database.create_application(
                app_type="PODPISANIE",
                applicant_id=interaction.user.id,
                player_name=gracz,
                player_discord_id=player_discord_id,
                target_club=kup,
                clause=klauz,
                expires_at=wazny_do,
                needs_player_agree=needs_player,
                needs_target_club_agree=needs_target,
                needs_source_club_agree=False
            )

            forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
            v_forum = ForumApplicationView(app_id)
            thread = await forum.create_thread(name=f"[{kup}] Nowy Gracz: {gracz}", embed=embed, view=v_forum)
            database.set_application_message(app_id, thread.thread.id, thread.message.id)
            await ping_representatives(thread.thread, kup)

        await kanal.delete()
    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_podpisania] Błąd: {e}\n{traceback.format_exc()}")
        try:
            await kanal.send(f"❌ Wystąpił błąd: {e}")
            await asyncio.sleep(5)
            await kanal.delete()
        except Exception:
            pass

# =========================================================================
# 3. PROCES TRANSFERU
# =========================================================================
async def proces_transferu(interaction: discord.Interaction):
    kanal = await utworz_kanal_ticket(interaction, "transfer")
    client = interaction.client
    try:
        await kanal.send(f"*Masz 15 minut na każdą odpowiedź.*")
        while True:
            kup = clean_tag(await zadaj_pytanie(kanal, interaction.user, "Skrót TWOJEGO KLUBU (Kupujący):", client))
            if not is_club_board_or_owner(interaction.user, kup):
                await kanal.send("❌ Brak uprawnień do tego klubu lub klub nie istnieje!")
                continue

            current_count = database.get_club_player_count(kup)
            if current_count >= MAX_PLAYERS_PER_CLUB:
                await kanal.send(f"❌ Twój klub osiągnął już maksymalny limit zawodników ({current_count}/{MAX_PLAYERS_PER_CLUB})! Transfer niemożliwy.")
                await asyncio.sleep(5)
                await kanal.delete()
                return
            break

        while True:
            sprzed = clean_tag(await zadaj_pytanie(kanal, interaction.user, "Skrót KLUBU SPRZEDAJĄCEGO:", client))
            if not database.get_club(sprzed):
                await kanal.send("❌ Ten klub nie istnieje w bazie!")
            elif sprzed == kup:
                await kanal.send("❌ Klub kupujący i sprzedający nie mogą być takie same!")
            else:
                break

        gracz = await zadaj_pytanie(kanal, interaction.user, "Oznacz @Zawodnika (lub wpisz Imię jeśli nie ma DC):", client)
        extracted_gracz = extract_ids(gracz)
        player_discord_id = extracted_gracz[0] if extracted_gracz else None

        kwota = await zadaj_pytanie(kanal, interaction.user, "Kwota transferu:", client)

        while True:
            czas_input = await zadaj_pytanie(kanal, interaction.user, "Długość nowego kontraktu (np. '60 dni' lub '31.12.2026'):", client)
            wazny_do = parse_expiry_date(czas_input)
            if wazny_do: break
            await kanal.send("❌ Błędny termin! Podaj liczbę dni lub datę DD.MM.RRRR.")

        klauz = await zadaj_pytanie(kanal, interaction.user, "Nowa Klauzula (lub wpisz 'Brak'):", client)

        # Sprawdzenie klauzuli istniejącego gracza
        czy_klauzula = False
        dane_gracza = database.get_player(gracz)
        if not dane_gracza and player_discord_id:
            dane_gracza = database.get_player_by_discord_id(player_discord_id)

        if dane_gracza and dane_gracza.get("clause") and dane_gracza["clause"].lower() != "brak":
            kwota_val = parse_amount(kwota)
            klauz_val = parse_amount(dane_gracza["clause"])
            if klauz_val > 0 and kwota_val >= klauz_val:
                czy_klauzula = True

        c_target = database.get_club(kup)
        c_source = database.get_club(sprzed)

        has_target_board_dc = bool(c_target and (c_target.get("board_ids") or c_target.get("reprezentant_dc")))
        has_source_board_dc = bool(c_source and (c_source.get("board_ids") or c_source.get("reprezentant_dc")))

        needs_player = bool(player_discord_id)
        needs_target = has_target_board_dc
        # Jeśli wykup klauzulowy -> zgoda sprzedającego zbędna. Jeśli brak klauzuli lub kwota mniejsza -> wymagana zgoda, o ile zarząd ma DC
        needs_source = (not czy_klauzula) and has_source_board_dc

        embed = discord.Embed(
            title=f"{'🔥 Wykup' if czy_klauzula else '🤝 Transfer'}: {gracz}",
            color=0xe67e22 if czy_klauzula else 0x9b59b6
        )
        embed.add_field(name="Kupujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Sprzedający", value=f"`{sprzed}`", inline=True)
        embed.add_field(name="Kwota", value=kwota, inline=True)
        embed.add_field(name="Nowa Klauzula", value=klauz, inline=True)
        embed.add_field(name="Wygasa", value=f"`{wazny_do}`", inline=False)

        source_status_text = "⚡ Wykup klauzulowy (zgoda zbędna)" if czy_klauzula else ("⏳ Oczekuje" if has_source_board_dc else "ℹ️ Brak oznaczonych kont zarządu")
        status_text = (
            f"• Zawodnik: {'⏳ Oczekuje' if needs_player else 'ℹ️ Brak konta Discord (kontakt poza DC)'}\n"
            f"• Klub `{kup}`: {'⏳ Oczekuje' if needs_target else 'ℹ️ Brak oznaczonych kont zarządu'}\n"
            f"• Klub `{sprzed}`: {source_status_text}\n"
            "• Zarząd Federacji: ⏳ Oczekuje na decyzję"
        )
        embed.add_field(name="Status", value=status_text, inline=False)

        view = WniosekConfirmView()
        await kanal.send(embed=embed, view=view)
        await view.wait()

        if view.value is None:
            await kanal.send("⏳ **Minęło 15 minut bez potwierdzenia.** Zamykam kanał...")
            await asyncio.sleep(3)
            await kanal.delete()
            return

        if view.value:
            app_id = database.create_application(
                app_type="TRANSFER",
                applicant_id=interaction.user.id,
                player_name=gracz,
                player_discord_id=player_discord_id,
                target_club=kup,
                source_club=sprzed,
                amount=kwota,
                clause=klauz,
                expires_at=wazny_do,
                needs_player_agree=needs_player,
                needs_target_club_agree=needs_target,
                needs_source_club_agree=needs_source
            )

            forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
            v_forum = ForumApplicationView(app_id)
            thread = await forum.create_thread(name=f"[{kup}] Transfer: {gracz}", embed=embed, view=v_forum)
            database.set_application_message(app_id, thread.thread.id, thread.message.id)
            await ping_representatives(thread.thread, kup, sprzed)

        await kanal.delete()
    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_transferu] Błąd: {e}\n{traceback.format_exc()}")
        try:
            await kanal.send(f"❌ Wystąpił błąd: {e}")
            await asyncio.sleep(5)
            await kanal.delete()
        except Exception:
            pass

# =========================================================================
# 4. PROCES WYPOŻYCZENIA
# =========================================================================
async def proces_wypozyczenia(interaction: discord.Interaction):
    kanal = await utworz_kanal_ticket(interaction, "wypozyczenie")
    client = interaction.client
    try:
        await kanal.send(f"*Masz 15 minut na każdą odpowiedź.*")
        while True:
            kup = clean_tag(await zadaj_pytanie(kanal, interaction.user, "Skrót KLUBU PRZYJMUJĄCEGO (Twój):", client))
            if not is_club_board_or_owner(interaction.user, kup):
                await kanal.send("❌ Odmowa dostępu lub klub nie istnieje!")
                continue

            current_count = database.get_club_player_count(kup)
            if current_count >= MAX_PLAYERS_PER_CLUB:
                await kanal.send(f"❌ Twój klub posiada już maksymalną liczbę zawodników ({current_count}/{MAX_PLAYERS_PER_CLUB})! Wypożyczenie niemożliwe.")
                await asyncio.sleep(5)
                await kanal.delete()
                return
            break

        while True:
            sprzed = clean_tag(await zadaj_pytanie(kanal, interaction.user, "Skrót KLUBU ODDAJĄCEGO:", client))
            if not database.get_club(sprzed):
                await kanal.send("❌ Ten klub nie istnieje w bazie!")
            elif sprzed == kup:
                await kanal.send("❌ Klub przyjmujący i oddający nie mogą być takie same!")
            else:
                break

        gracz = await zadaj_pytanie(kanal, interaction.user, "Oznacz @Zawodnika (lub wpisz Imię jeśli nie ma DC):", client)
        extracted_gracz = extract_ids(gracz)
        player_discord_id = extracted_gracz[0] if extracted_gracz else None

        while True:
            czas_input = await zadaj_pytanie(kanal, interaction.user, "Okres wypożyczenia (np. '30 dni' lub '15.01.2027'):", client)
            wazny_do = parse_expiry_date(czas_input)
            if wazny_do: break
            await kanal.send("❌ Błędny termin! Podaj liczbę dni lub datę DD.MM.RRRR.")

        kwota = await zadaj_pytanie(kanal, interaction.user, "Opłata za wypożyczenie (lub 'Brak'):", client)

        c_target = database.get_club(kup)
        c_source = database.get_club(sprzed)

        has_target_board_dc = bool(c_target and (c_target.get("board_ids") or c_target.get("reprezentant_dc")))
        has_source_board_dc = bool(c_source and (c_source.get("board_ids") or c_source.get("reprezentant_dc")))

        needs_player = bool(player_discord_id)
        needs_target = has_target_board_dc
        needs_source = has_source_board_dc

        embed = discord.Embed(title=f"⏱️ Wypożyczenie: {gracz}", color=0x1abc9c)
        embed.add_field(name="Przyjmujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Oddający", value=f"`{sprzed}`", inline=True)
        embed.add_field(name="Opłata", value=kwota, inline=True)
        embed.add_field(name="Koniec wypożyczenia", value=f"`{wazny_do}`", inline=False)

        status_text = (
            f"• Zawodnik: {'⏳ Oczekuje' if needs_player else 'ℹ️ Brak konta Discord (kontakt poza DC)'}\n"
            f"• Klub `{kup}`: {'⏳ Oczekuje' if needs_target else 'ℹ️ Brak oznaczonych kont zarządu'}\n"
            f"• Klub `{sprzed}`: {'⏳ Oczekuje' if needs_source else 'ℹ️ Brak oznaczonych kont zarządu'}\n"
            "• Zarząd Federacji: ⏳ Oczekuje na decyzję"
        )
        embed.add_field(name="Status", value=status_text, inline=False)

        view = WniosekConfirmView()
        await kanal.send(embed=embed, view=view)
        await view.wait()

        if view.value is None:
            await kanal.send("⏳ **Minęło 15 minut bez potwierdzenia.** Zamykam kanał...")
            await asyncio.sleep(3)
            await kanal.delete()
            return

        if view.value:
            app_id = database.create_application(
                app_type="WYPOZYCZENIE",
                applicant_id=interaction.user.id,
                player_name=gracz,
                player_discord_id=player_discord_id,
                target_club=kup,
                source_club=sprzed,
                amount=kwota,
                clause="Bez zmian",
                expires_at=wazny_do,
                needs_player_agree=needs_player,
                needs_target_club_agree=needs_target,
                needs_source_club_agree=needs_source
            )

            forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
            v_forum = ForumApplicationView(app_id)
            thread = await forum.create_thread(name=f"[{kup}] Wypożyczenie: {gracz}", embed=embed, view=v_forum)
            database.set_application_message(app_id, thread.thread.id, thread.message.id)
            await ping_representatives(thread.thread, kup, sprzed)

        await kanal.delete()
    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_wypozyczenia] Błąd: {e}\n{traceback.format_exc()}")
        try:
            await kanal.send(f"❌ Wystąpił błąd: {e}")
            await asyncio.sleep(5)
            await kanal.delete()
        except Exception:
            pass
