import asyncio
import traceback
import discord
from discord import ui
import database
from config import ROLE_FEDERACJA_ID, CHANNEL_FORUM_ID, MAX_PLAYERS_PER_CLUB
from utils.helpers import (
    clean_tag, extract_ids, parse_expiry_date, parse_amount, validate_amount_input,
    is_club_board_or_owner, ping_representatives, send_dm
)
from views.confirmation import WniosekConfirmView
from views.application_view import ForumApplicationView

async def _create_ticket_channel(guild: discord.Guild, user: discord.Member, prefix: str) -> discord.TextChannel:
    """Tworzy tymczasowy kanał ticketu z uprawnieniami."""
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    rola_fed = guild.get_role(ROLE_FEDERACJA_ID)
    if rola_fed:
        overwrites[rola_fed] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    ticket_id = database.get_next_ticket_id()
    channel_name = f"{prefix}-{ticket_id}"
    return await guild.create_text_channel(channel_name, overwrites=overwrites)

async def _zadaj_pytanie(kanal: discord.TextChannel, uzytkownik: discord.Member,
                          pytanie: str, client: discord.Client) -> str:
    """Wysyła pytanie i czeka na odpowiedź. Timeout = 15 min."""
    await kanal.send(f"🤖 **[Pytanie]** {pytanie}")

    def check(m):
        return m.author == uzytkownik and m.channel == kanal

    try:
        msg = await client.wait_for('message', check=check, timeout=900.0)
        return msg.content.strip()
    except asyncio.TimeoutError:
        await kanal.send("⏳ **Minęło 15 minut braku aktywności.** Wniosek anulowany, usuwam kanał...")
        await asyncio.sleep(3)
        try:
            await kanal.delete()
        except Exception:
            pass
        raise TimeoutError("Timeout ankiety")

async def _send_forum_application(
    guild: discord.Guild, kanal: discord.TextChannel,
    embed: discord.Embed, thread_name: str, app_id: int,
    ping_target: str = None, ping_source: str = None
):
    """Wysyła wniosek na forum, zapisuje message_id i usuwa kanał ticketu."""
    forum = guild.get_channel(CHANNEL_FORUM_ID)
    v_forum = ForumApplicationView(app_id)
    thread = await forum.create_thread(name=thread_name, embed=embed, view=v_forum)
    database.set_application_message(app_id, thread.thread.id, thread.message.id)

    if ping_target or ping_source:
        await ping_representatives(thread.thread, ping_target, ping_source)

    # Natychmiastowe usunięcie kanału ticketu po wysłaniu wniosku
    await kanal.send("✅ Wniosek wysłany na forum! Zamykam kanał...")
    await asyncio.sleep(2)
    try:
        await kanal.delete()
    except Exception:
        pass

    return thread.thread

# =========================================================================
# 1. REJESTRACJA KLUBU
# =========================================================================
async def proces_rejestracji_klubu(interaction: discord.Interaction):
    guild = interaction.guild
    user = interaction.user
    kanal = await _create_ticket_channel(guild, user, "rejestracja")
    client = interaction.client

    try:
        await interaction.followup.send(f"Utworzono kanał: {kanal.mention}", ephemeral=True)
        await kanal.send(
            f"Witaj {user.mention}! Rozpoczynamy rejestrację klubu.\n"
            "*Masz 15 minut na każdą odpowiedź. Timeout kasuje kanał automatycznie.*"
        )

        nazwa = await _zadaj_pytanie(kanal, user, "Podaj pełną nazwę drużyny (np. FC Łazy):", client)

        while True:
            skrot = await _zadaj_pytanie(
                kanal, user, "Podaj skrót drużyny (Dokładnie **3 litery**, np. LAZ):", client)
            skrot = clean_tag(skrot)
            if len(skrot) != 3:
                await kanal.send("❌ Skrót musi mieć dokładnie 3 litery!")
            elif database.get_club(skrot):
                await kanal.send(f"❌ Skrót `{skrot}` jest już zajęty!")
            else:
                break

        zalozyciel = await _zadaj_pytanie(
            kanal, user, "Oznacz @Głównego Założyciela (lub wpisz Imię jeśli nie ma DC):", client)
        zarzad = await _zadaj_pytanie(
            kanal, user, "Oznacz @Pozostały Zarząd (lub wpisz 'Brak'):", client)

        embed = discord.Embed(title=f"🏛️ Podsumowanie: {nazwa}", color=0x2b2d31)
        embed.add_field(name="Skrót", value=f"`{skrot}`", inline=True)
        embed.add_field(name="Założyciel", value=zalozyciel, inline=True)
        embed.add_field(name="Zarząd", value=zarzad, inline=False)
        embed.add_field(name="Status", value="⏳ Oczekuje na decyzję Zarządu Federacji", inline=False)

        view = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=view)
        await view.wait()

        if view.value is None or view.value is False:
            await kanal.send("❌ Wniosek anulowany. Usuwam kanał...")
            await asyncio.sleep(2)
            await kanal.delete()
            return

        app_id = database.create_application(
            app_type="REJESTRACJA_KLUBU",
            applicant_id=user.id,
            club_name=nazwa, club_tag=skrot,
            founder_txt=zalozyciel, board_txt=zarzad
        )

        await _send_forum_application(
            guild, kanal, embed, f"[{skrot}] Rejestracja: {nazwa}", app_id
        )

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_rejestracji_klubu] Błąd: {e}\n{traceback.format_exc()}")
        try:
            await kanal.send(f"❌ Wystąpił błąd: `{e}`")
            await asyncio.sleep(5)
            await kanal.delete()
        except Exception:
            pass

# =========================================================================
# 2. PODPISANIE GRACZA (BEZ KLUBU)
# =========================================================================
async def proces_podpisania(interaction: discord.Interaction):
    guild = interaction.guild
    user = interaction.user
    kanal = await _create_ticket_channel(guild, user, "kontrakt")
    client = interaction.client

    try:
        await interaction.followup.send(f"Utworzono kanał: {kanal.mention}", ephemeral=True)
        await kanal.send("*Masz 15 minut na każdą odpowiedź.*")

        # ── Weryfikacja klubu kupującego ──
        while True:
            kup = clean_tag(await _zadaj_pytanie(kanal, user, "Podaj skrót TWOJEGO KLUBU (kupującego):", client))
            if not database.get_club(kup):
                await kanal.send("❌ Klub nie istnieje w bazie!")
            elif not is_club_board_or_owner(user, kup):
                await kanal.send("❌ Nie jesteś w zarządzie tego klubu!")
            elif database.get_club_player_count(kup) >= MAX_PLAYERS_PER_CLUB:
                await kanal.send(
                    f"❌ Twój klub ma już maksymalną liczbę zawodników "
                    f"({MAX_PLAYERS_PER_CLUB}/{MAX_PLAYERS_PER_CLUB}). Podpisanie niemożliwe."
                )
                await asyncio.sleep(5)
                await kanal.delete()
                return
            else:
                break

        # ── Zawodnik ──
        gracz = await _zadaj_pytanie(
            kanal, user, "Oznacz @Zawodnika (lub wpisz jego imię jeśli nie ma DC):", client)
        extracted = extract_ids(gracz)
        player_dc_id = extracted[0] if extracted else None

        # ── Blokada kradzieży – sprawdzenie czy gracz nie gra już gdzieś ──
        existing = database.is_player_under_contract(gracz, player_dc_id)
        if existing:
            current_club = existing.get("club_tag", "innym klubie")
            await kanal.send(
                f"❌ **Ten zawodnik ma już aktywny kontrakt z klubem `{current_club}`!**\n"
                "Aby go pozyskać, złóż **Wniosek Transferowy** zamiast Podpisania Gracza."
            )
            await asyncio.sleep(5)
            await kanal.delete()
            return

        # ── Długość kontraktu ──
        while True:
            czas_input = await _zadaj_pytanie(
                kanal, user,
                "Podaj długość kontraktu (np. `30` lub `30 dni`, albo datę `30.06.2027`):",
                client
            )
            wazny_do = parse_expiry_date(czas_input)
            if wazny_do:
                break
            await kanal.send("❌ Nieprawidłowy format lub data z przeszłości! Wpisz liczbę dni (np. `14`) lub przyszłą datę `DD.MM.RRRR`.")

        # ── Klauzula ──
        while True:
            klauz = await _zadaj_pytanie(kanal, user, "Podaj kwotę Klauzuli (np. `5000`) lub wpisz `Brak`:", client)
            if validate_amount_input(klauz):
                break
            await kanal.send("❌ Podaj prawidłową kwotę (np. `5000`) lub wpisz `Brak`.")

        # ── Podsumowanie ──
        c_target = database.get_club(kup)
        has_target_dc = bool(c_target and (c_target.get("board_ids") or c_target.get("reprezentant_dc")))
        needs_player = bool(player_dc_id)
        needs_target = has_target_dc

        embed = discord.Embed(title=f"📄 Podpisanie Gracza: {gracz}", color=0x3498db)
        embed.add_field(name="Kupujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Wygasa", value=f"`{wazny_do}`", inline=True)
        embed.add_field(name="Klauzula", value=f"`{klauz}`", inline=True)

        status_lines = [
            f"• Zawodnik: {'⏳ Oczekuje' if needs_player else 'ℹ️ Brak konta Discord (kontakt poza DC)'}",
            f"• Klub `{kup}`: {'⏳ Oczekuje' if needs_target else 'ℹ️ Brak oznaczonych kont DC zarządu'}",
            "• Zarząd Federacji: ⏳ Oczekuje na decyzję"
        ]
        embed.add_field(name="Status", value="\n".join(status_lines), inline=False)

        view = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=view)
        await view.wait()

        if view.value is None or view.value is False:
            await kanal.send("❌ Wniosek anulowany. Usuwam kanał...")
            await asyncio.sleep(2)
            await kanal.delete()
            return

        app_id = database.create_application(
            app_type="PODPISANIE", applicant_id=user.id,
            player_name=gracz, player_discord_id=player_dc_id,
            target_club=kup, clause=klauz, expires_at=wazny_do,
            needs_player_agree=needs_player, needs_target_club_agree=needs_target
        )

        thread = await _send_forum_application(
            guild, kanal, embed, f"[{kup}] Nowy Gracz: {gracz}", app_id, ping_target=kup
        )

        # DM do gracza z linkiem do wątku
        if player_dc_id:
            await send_dm(
                client, player_dc_id,
                f"📩 **Masz nowy wniosek podpisania!**\n"
                f"Klub `{kup}` złożył wniosek o Twoje podpisanie.\n"
                f"🔗 Kliknij, aby otworzyć wniosek: {thread.jump_url}"
            )

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_podpisania] Błąd: {e}\n{traceback.format_exc()}")
        try:
            await kanal.send(f"❌ Wystąpił błąd: `{e}`")
            await asyncio.sleep(5)
            await kanal.delete()
        except Exception:
            pass

# =========================================================================
# 3. WNIOSEK TRANSFEROWY
# =========================================================================
async def proces_transferu(interaction: discord.Interaction):
    guild = interaction.guild
    user = interaction.user
    kanal = await _create_ticket_channel(guild, user, "transfer")
    client = interaction.client

    try:
        await interaction.followup.send(f"Utworzono kanał: {kanal.mention}", ephemeral=True)
        await kanal.send("*Masz 15 minut na każdą odpowiedź.*")

        # ── Klub kupujący ──
        while True:
            kup = clean_tag(await _zadaj_pytanie(kanal, user, "Skrót TWOJEGO KLUBU (Kupujący):", client))
            if not database.get_club(kup):
                await kanal.send("❌ Klub nie istnieje w bazie!")
            elif not is_club_board_or_owner(user, kup):
                await kanal.send("❌ Odmowa dostępu – nie jesteś w zarządzie tego klubu!")
            elif database.get_club_player_count(kup) >= MAX_PLAYERS_PER_CLUB:
                await kanal.send(
                    f"❌ Twój klub ma już limit zawodników ({MAX_PLAYERS_PER_CLUB}/{MAX_PLAYERS_PER_CLUB}). Transfer niemożliwy.")
                await asyncio.sleep(5)
                await kanal.delete()
                return
            else:
                break

        # ── Klub sprzedający ──
        while True:
            sprzed = clean_tag(await _zadaj_pytanie(kanal, user, "Skrót KLUBU SPRZEDAJĄCEGO:", client))
            if not database.get_club(sprzed):
                await kanal.send("❌ Ten klub nie istnieje w bazie!")
            elif sprzed == kup:
                await kanal.send("❌ Klub kupujący i sprzedający nie mogą być identyczne!")
            else:
                break

        # ── Zawodnik + weryfikacja przynależności ──
        while True:
            gracz = await _zadaj_pytanie(
                kanal, user, "Oznacz @Zawodnika (lub wpisz Imię jeśli nie ma DC):", client)
            extracted = extract_ids(gracz)
            player_dc_id = extracted[0] if extracted else None

            # Sprawdź czy gracz faktycznie należy do klubu sprzedającego
            existing = database.is_player_under_contract(gracz, player_dc_id)
            if existing and existing.get("club_tag", "").upper() != sprzed:
                actual_club = existing.get("club_tag", "?")
                await kanal.send(
                    f"❌ **Zawodnik `{gracz}` należy do klubu `{actual_club}`, "
                    f"a nie do `{sprzed}`!**\n Wskaż prawidłowy klub sprzedający lub zmień zawodnika."
                )
            else:
                break

        # ── Kwota transferu ──
        while True:
            kwota = await _zadaj_pytanie(kanal, user, "Kwota transferu (np. `10000`):", client)
            if validate_amount_input(kwota):
                break
            await kanal.send("❌ Podaj prawidłową kwotę (np. `10000`).")

        # ── Długość nowego kontraktu ──
        while True:
            czas_input = await _zadaj_pytanie(
                kanal, user, "Długość nowego kontraktu (np. `60 dni` lub `31.12.2026`):", client)
            wazny_do = parse_expiry_date(czas_input)
            if wazny_do:
                break
            await kanal.send("❌ Błędny termin! Podaj liczbę dni lub datę `DD.MM.RRRR`.")

        # ── Nowa klauzula ──
        while True:
            klauz = await _zadaj_pytanie(kanal, user, "Nowa Klauzula (np. `15000`) lub wpisz `Brak`:", client)
            if validate_amount_input(klauz):
                break
            await kanal.send("❌ Podaj prawidłową kwotę (np. `15000`) lub wpisz `Brak`.")

        # ── Sprawdzenie wykupu klauzulowego ──
        czy_klauzula = False
        dane_gracza = database.get_player(gracz)
        if not dane_gracza and player_dc_id:
            dane_gracza = database.get_player_by_discord_id(player_dc_id)

        if dane_gracza:
            old_clause = dane_gracza.get("clause", "Brak")
            kwota_val = parse_amount(kwota)
            klauz_old_val = parse_amount(old_clause)
            if klauz_old_val > 0 and kwota_val >= klauz_old_val:
                czy_klauzula = True

        c_target = database.get_club(kup)
        c_source = database.get_club(sprzed)
        has_target_dc = bool(c_target and (c_target.get("board_ids") or c_target.get("reprezentant_dc")))
        has_source_dc = bool(c_source and (c_source.get("board_ids") or c_source.get("reprezentant_dc")))

        needs_player = bool(player_dc_id)
        needs_target = has_target_dc
        needs_source = (not czy_klauzula) and has_source_dc

        embed = discord.Embed(
            title=f"{'🔥 Wykup Klauzulowy' if czy_klauzula else '🤝 Transfer'}: {gracz}",
            color=0xe67e22 if czy_klauzula else 0x9b59b6
        )
        embed.add_field(name="Kupujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Sprzedający", value=f"`{sprzed}`", inline=True)
        embed.add_field(name="Kwota", value=f"`{kwota}`", inline=True)
        embed.add_field(name="Nowa Klauzula", value=f"`{klauz}`", inline=True)
        embed.add_field(name="Wygasa", value=f"`{wazny_do}`", inline=False)

        source_info = "⚡ Zgoda zbędna (wykup klauzulowy)" if czy_klauzula else \
            ("⏳ Oczekuje" if has_source_dc else "ℹ️ Brak kont DC zarządu")
        status_lines = [
            f"• Zawodnik: {'⏳ Oczekuje' if needs_player else 'ℹ️ Brak konta Discord'}",
            f"• Klub `{kup}`: {'⏳ Oczekuje' if needs_target else 'ℹ️ Brak kont DC zarządu'}",
            f"• Klub `{sprzed}`: {source_info}",
            "• Zarząd Federacji: ⏳ Oczekuje na decyzję"
        ]
        embed.add_field(name="Status", value="\n".join(status_lines), inline=False)

        view = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=view)
        await view.wait()

        if view.value is None or view.value is False:
            await kanal.send("❌ Wniosek anulowany. Usuwam kanał...")
            await asyncio.sleep(2)
            await kanal.delete()
            return

        app_id = database.create_application(
            app_type="TRANSFER", applicant_id=user.id,
            player_name=gracz, player_discord_id=player_dc_id,
            target_club=kup, source_club=sprzed,
            amount=kwota, clause=klauz, expires_at=wazny_do,
            needs_player_agree=needs_player,
            needs_target_club_agree=needs_target,
            needs_source_club_agree=needs_source
        )

        thread = await _send_forum_application(
            guild, kanal, embed, f"[{kup}] Transfer: {gracz}", app_id,
            ping_target=kup, ping_source=sprzed
        )

        # DM do gracza
        if player_dc_id:
            await send_dm(
                client, player_dc_id,
                f"📩 **Masz nowy wniosek transferowy!**\n"
                f"Klub `{kup}` złożył wniosek o Twój transfer.\n"
                f"🔗 Kliknij, aby otworzyć wniosek: {thread.jump_url}"
            )

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_transferu] Błąd: {e}\n{traceback.format_exc()}")
        try:
            await kanal.send(f"❌ Wystąpił błąd: `{e}`")
            await asyncio.sleep(5)
            await kanal.delete()
        except Exception:
            pass

# =========================================================================
# 4. WYPOŻYCZENIE
# =========================================================================
async def proces_wypozyczenia(interaction: discord.Interaction):
    guild = interaction.guild
    user = interaction.user
    kanal = await _create_ticket_channel(guild, user, "wypozyczenie")
    client = interaction.client

    try:
        await interaction.followup.send(f"Utworzono kanał: {kanal.mention}", ephemeral=True)
        await kanal.send("*Masz 15 minut na każdą odpowiedź.*")

        # ── Klub przyjmujący ──
        while True:
            kup = clean_tag(await _zadaj_pytanie(
                kanal, user, "Skrót KLUBU PRZYJMUJĄCEGO (Twojego):", client))
            if not database.get_club(kup):
                await kanal.send("❌ Klub nie istnieje w bazie!")
            elif not is_club_board_or_owner(user, kup):
                await kanal.send("❌ Odmowa dostępu – nie jesteś w zarządzie tego klubu!")
            elif database.get_club_player_count(kup) >= MAX_PLAYERS_PER_CLUB:
                await kanal.send(
                    f"❌ Twój klub ma już limit zawodników ({MAX_PLAYERS_PER_CLUB}/{MAX_PLAYERS_PER_CLUB}). Wypożyczenie niemożliwe.")
                await asyncio.sleep(5)
                await kanal.delete()
                return
            else:
                break

        # ── Klub oddający ──
        while True:
            sprzed = clean_tag(await _zadaj_pytanie(kanal, user, "Skrót KLUBU ODDAJĄCEGO:", client))
            if not database.get_club(sprzed):
                await kanal.send("❌ Ten klub nie istnieje w bazie!")
            elif sprzed == kup:
                await kanal.send("❌ Klub przyjmujący i oddający nie mogą być identyczne!")
            else:
                break

        # ── Zawodnik + weryfikacja przynależności ──
        while True:
            gracz = await _zadaj_pytanie(
                kanal, user, "Oznacz @Zawodnika (lub wpisz Imię jeśli nie ma DC):", client)
            extracted = extract_ids(gracz)
            player_dc_id = extracted[0] if extracted else None

            existing = database.is_player_under_contract(gracz, player_dc_id)
            if existing and existing.get("club_tag", "").upper() != sprzed:
                actual_club = existing.get("club_tag", "?")
                await kanal.send(
                    f"❌ Zawodnik `{gracz}` należy do `{actual_club}`, "
                    f"a nie do `{sprzed}`! Wskaż prawidłowy klub oddający."
                )
            else:
                break

        # ── Okres wypożyczenia ──
        while True:
            czas_input = await _zadaj_pytanie(
                kanal, user, "Okres wypożyczenia (np. `30 dni` lub `15.01.2027`):", client)
            wazny_do = parse_expiry_date(czas_input)
            if wazny_do:
                break
            await kanal.send("❌ Błędny termin! Podaj liczbę dni lub datę `DD.MM.RRRR`.")

        # ── Opłata ──
        while True:
            kwota = await _zadaj_pytanie(
                kanal, user, "Opłata za wypożyczenie (np. `2000`) lub wpisz `Brak`:", client)
            if validate_amount_input(kwota):
                break
            await kanal.send("❌ Podaj prawidłową kwotę (np. `2000`) lub wpisz `Brak`.")

        c_target = database.get_club(kup)
        c_source = database.get_club(sprzed)
        has_target_dc = bool(c_target and (c_target.get("board_ids") or c_target.get("reprezentant_dc")))
        has_source_dc = bool(c_source and (c_source.get("board_ids") or c_source.get("reprezentant_dc")))

        needs_player = bool(player_dc_id)
        needs_target = has_target_dc
        needs_source = has_source_dc

        embed = discord.Embed(title=f"⏱️ Wypożyczenie: {gracz}", color=0x1abc9c)
        embed.add_field(name="Przyjmujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Oddający", value=f"`{sprzed}`", inline=True)
        embed.add_field(name="Opłata", value=f"`{kwota}`", inline=True)
        embed.add_field(name="Koniec wypożyczenia", value=f"`{wazny_do}`", inline=False)

        status_lines = [
            f"• Zawodnik: {'⏳ Oczekuje' if needs_player else 'ℹ️ Brak konta Discord'}",
            f"• Klub `{kup}`: {'⏳ Oczekuje' if needs_target else 'ℹ️ Brak kont DC zarządu'}",
            f"• Klub `{sprzed}`: {'⏳ Oczekuje' if needs_source else 'ℹ️ Brak kont DC zarządu'}",
            "• Zarząd Federacji: ⏳ Oczekuje na decyzję"
        ]
        embed.add_field(name="Status", value="\n".join(status_lines), inline=False)

        view = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=view)
        await view.wait()

        if view.value is None or view.value is False:
            await kanal.send("❌ Wniosek anulowany. Usuwam kanał...")
            await asyncio.sleep(2)
            await kanal.delete()
            return

        app_id = database.create_application(
            app_type="WYPOZYCZENIE", applicant_id=user.id,
            player_name=gracz, player_discord_id=player_dc_id,
            target_club=kup, source_club=sprzed,
            amount=kwota, clause="Bez zmian", expires_at=wazny_do,
            needs_player_agree=needs_player,
            needs_target_club_agree=needs_target,
            needs_source_club_agree=needs_source
        )

        thread = await _send_forum_application(
            guild, kanal, embed, f"[{kup}] Wypożyczenie: {gracz}", app_id,
            ping_target=kup, ping_source=sprzed
        )

        if player_dc_id:
            await send_dm(
                client, player_dc_id,
                f"📩 **Masz nowy wniosek wypożyczenia!**\n"
                f"Klub `{kup}` złożył wniosek o Twoje wypożyczenie.\n"
                f"🔗 Kliknij, aby otworzyć wniosek: {thread.jump_url}"
            )

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_wypozyczenia] Błąd: {e}\n{traceback.format_exc()}")
        try:
            await kanal.send(f"❌ Wystąpił błąd: `{e}`")
            await asyncio.sleep(5)
            await kanal.delete()
        except Exception:
            pass
