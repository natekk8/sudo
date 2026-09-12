import asyncio
import traceback
import discord
from discord import ui
import database
from config import ROLE_FEDERACJA_ID, CHANNEL_FORUM_ID, MAX_PLAYERS_PER_CLUB
import utils.league_config as league_config

from utils.helpers import (
    clean_tag, is_valid_tag, extract_ids, parse_expiry_date,
    parse_amount, validate_amount_input, is_club_board_or_owner,
    ping_representatives, send_dm, has_open_ticket, safe_thread_name, get_now_warsaw,
    resolve_player_identity, clean_player_name
)
from views.confirmation import WniosekConfirmView
from views.application_view import ForumApplicationView




async def _create_ticket_channel(guild: discord.Guild, user: discord.Member, prefix: str) -> discord.TextChannel:
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    rola_fed = guild.get_role(league_config.role_federacja_id() or ROLE_FEDERACJA_ID)
    if rola_fed:
        overwrites[rola_fed] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    ticket_id = database.get_next_ticket_id()
    return await guild.create_text_channel(f"{prefix}-{ticket_id}", overwrites=overwrites)


async def _zadaj_pytanie(kanal, uzytkownik, pytanie, client) -> str:
    await kanal.send(embed=discord.Embed(description=f"âť“ {pytanie}", color=0x3498db))

    def check(m):
        return m.author == uzytkownik and m.channel == kanal

    try:
        msg = await client.wait_for('message', check=check, timeout=900.0)
        return msg.content.strip()
    except asyncio.TimeoutError:
        await kanal.send(embed=discord.Embed(title="âŹł UpĹ‚ynÄ…Ĺ‚ czas", description=f" **MinÄ™Ĺ‚o 15 minut braku aktywnoĹ›ci.** Wniosek anulowany.", color=0xf39c12))
        await asyncio.sleep(3)
        try:
            await kanal.delete()
        except Exception:
            pass
        raise TimeoutError("Timeout ankiety")


async def _send_forum_application(guild, kanal, embed, thread_name, app_id,
                                   ping_target=None, ping_source=None):
    forum = guild.get_channel(league_config.channel_forum_id() or CHANNEL_FORUM_ID)
    v = ForumApplicationView(app_id)
    safe_name = safe_thread_name(thread_name)
    thread = await forum.create_thread(name=safe_name, embed=embed, view=v)
    database.set_application_message(app_id, thread.thread.id, thread.message.id)
    if ping_target or ping_source:
        await ping_representatives(thread.thread, ping_target, ping_source)
    await kanal.send(embed=discord.Embed(description=f"âś… Wniosek wysĹ‚any na forum! Zamykam kanaĹ‚...", color=0x2ecc71))
    await asyncio.sleep(2)
    try:
        await kanal.delete()
    except Exception:
        pass
    return thread.thread


def _check_spam(guild, user, interaction) -> bool:
    """Zwraca True jeĹ›li uĹĽytkownik ma juĹĽ otwarty ticket (blokada spamu)."""
    if has_open_ticket(guild, user.id):
        return True
    return False


# =========================================================================
# 1. REJESTRACJA KLUBU
# =========================================================================
async def proces_rejestracji_klubu(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("âťŚ Masz juĹĽ otwarty kanaĹ‚ wniosku. DokoĹ„cz go lub poczekaj.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "rejestracja")
    try:
        await interaction.followup.send(f"KanaĹ‚: {kanal.mention}", ephemeral=True)
        embed_start = discord.Embed(title="đźŹ›ď¸Ź Rejestracja Nowego Klubu", description=f"Witaj {user.mention}! Bot poprowadzi CiÄ™ przez proces.\n> Masz **15 minut** na kaĹĽdÄ… odpowiedĹş.", color=0x2b2d31)
        embed_start.set_footer(text=f"{league_config.league_name()} • Biuro")
        await kanal.send(embed=embed_start)

        nazwa = await _zadaj_pytanie(kanal, user, "Podaj peĹ‚nÄ… nazwÄ™ druĹĽyny (np. FC Ĺazy):", client)

        while True:
            skrot = clean_tag(await _zadaj_pytanie(kanal, user, "Podaj skrĂłt (dokĹ‚adnie **3 litery/cyfry**, np. LAZ):", client))
            if not is_valid_tag(skrot):
                await kanal.send(embed=discord.Embed(description=f"âťŚ SkrĂłt musi skĹ‚adaÄ‡ siÄ™ dokĹ‚adnie z 3 liter lub cyfr (A-Z, 0-9)!", color=0xe74c3c))
            elif database.get_club(skrot):
                await kanal.send(embed=discord.Embed(description=f"âťŚ SkrĂłt `{skrot}` jest juĹĽ zajÄ™ty!", color=0xe74c3c))
            else:
                break

        wlasciciel = await _zadaj_pytanie(kanal, user, "Oznacz @WĹ‚aĹ›ciciela Klubu (lub wpisz imiÄ™ jeĹ›li brak DC):", client)
        zarzad = await _zadaj_pytanie(kanal, user, "Oznacz @PozostaĹ‚y ZarzÄ…d (lub wpisz 'Brak'):", client)

        embed = discord.Embed(title=f"đźŹ›ď¸Ź Podsumowanie: {nazwa}", color=0x2b2d31)
        embed.add_field(name="SkrĂłt", value=f"`{skrot}`", inline=True)
        embed.add_field(name="WĹ‚aĹ›ciciel", value=wlasciciel, inline=True)
        embed.add_field(name="ZarzÄ…d", value=zarzad, inline=False)
        embed.add_field(name="Status", value="âŹł Oczekuje na decyzjÄ™ ZarzÄ…du Federacji", inline=False)

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description=f"âťŚ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2)
            await kanal.delete()
            return

        app_id = database.create_application(
            app_type="REJESTRACJA_KLUBU", applicant_id=user.id,
            club_name=nazwa, club_tag=skrot, founder_txt=wlasciciel, board_txt=zarzad
        )
        await _send_forum_application(guild, kanal, embed, f"[{skrot}] Rejestracja: {nazwa}", app_id)

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_rejestracji_klubu] BĹ‚Ä…d: {e}\n{traceback.format_exc()}")
        try:
            await kanal.send(embed=discord.Embed(description=f"âťŚ BĹ‚Ä…d: `{e}`", color=0xe74c3c))
            await asyncio.sleep(5)
            await kanal.delete()
        except Exception:
            pass


# =========================================================================
# 2. PODPISANIE GRACZA
# =========================================================================
async def proces_podpisania(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if not database.is_market_open():
        return await interaction.followup.send(
            "â›” **Rynek transferowy jest obecnie ZAMKNIÄTY!**\n"
            "> SkĹ‚adanie wnioskĂłw kontraktowych, transferĂłw i wypoĹĽyczeĹ„ zostaĹ‚o wstrzymane przez ZarzÄ…d Federacji.",
            ephemeral=True
        )
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("âťŚ Masz juĹĽ otwarty kanaĹ‚ wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "kontrakt")
    try:
        await interaction.followup.send(f"KanaĹ‚: {kanal.mention}", ephemeral=True)
        await kanal.send("*Masz 15 minut na kaĹĽdÄ… odpowiedĹş.*")

        while True:
            kup = clean_tag(await _zadaj_pytanie(kanal, user, "Podaj skrĂłt TWOJEGO KLUBU (kupujÄ…cego):", client))
            if not database.get_club(kup):
                await kanal.send(embed=discord.Embed(description=f"âťŚ Klub nie istnieje!", color=0xe74c3c))
            elif not is_club_board_or_owner(user, kup):
                await kanal.send(embed=discord.Embed(description=f"âťŚ Nie jesteĹ› w zarzÄ…dzie tego klubu!", color=0xe74c3c))
            elif database.get_club_player_count(kup) >= league_config.max_players():
                await kanal.send(embed=discord.Embed(description=f"âťŚ Klub peĹ‚ny ({league_config.max_players()}/{league_config.max_players()}). Podpisanie niemoĹĽliwe.", color=0xe74c3c))
                await asyncio.sleep(5)
                await kanal.delete()
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
            await kanal.delete()
            return

        while True:
            czas = await _zadaj_pytanie(kanal, user, "Długość kontraktu (np. `30`, `30 dni`, `30.06.2027`):", client)
            wazny_do = parse_expiry_date(czas)
            if wazny_do: break
            await kanal.send(embed=discord.Embed(description=f"❌ Błędny format. Wpisz liczbę dni (np. `14`) lub datę `DD.MM.RRRR`.", color=0xe74c3c))

        while True:
            klauz = await _zadaj_pytanie(kanal, user, "Kwota Klauzuli (np. `5000`) lub `Brak`:", client)
            if validate_amount_input(klauz): break
            await kanal.send(embed=discord.Embed(description=f"❌ Podaj prawidłową kwotę (np. `5000`) lub `Brak`.", color=0xe74c3c))

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
            await kanal.send(embed=discord.Embed(description=f"❌ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2)
            await kanal.delete()
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
        print(f"[proces_podpisania] BĹ‚Ä…d: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"âťŚ BĹ‚Ä…d: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await kanal.delete()
        except Exception: pass


# =========================================================================
# 3. TRANSFER
# =========================================================================
async def proces_transferu(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if not database.is_market_open():
        return await interaction.followup.send(
            "â›” **Rynek transferowy jest obecnie ZAMKNIÄTY!**\n"
            "> SkĹ‚adanie wnioskĂłw kontraktowych, transferĂłw i wypoĹĽyczeĹ„ zostaĹ‚o wstrzymane przez ZarzÄ…d Federacji.",
            ephemeral=True
        )
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("âťŚ Masz juĹĽ otwarty kanaĹ‚ wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "transfer")
    try:
        await interaction.followup.send(f"KanaĹ‚: {kanal.mention}", ephemeral=True)
        await kanal.send("*Masz 15 minut na kaĹĽdÄ… odpowiedĹş.*")

        while True:
            kup = clean_tag(await _zadaj_pytanie(kanal, user, "SkrĂłt TWOJEGO KLUBU (KupujÄ…cy):", client))
            if not database.get_club(kup):
                await kanal.send(embed=discord.Embed(description=f"âťŚ Klub nie istnieje!", color=0xe74c3c))
            elif not is_club_board_or_owner(user, kup):
                await kanal.send(embed=discord.Embed(description=f"âťŚ Odmowa â€“ nie jesteĹ› w zarzÄ…dzie tego klubu!", color=0xe74c3c))
            elif database.get_club_player_count(kup) >= league_config.max_players():
                await kanal.send(embed=discord.Embed(description=f"âťŚ Klub peĹ‚ny ({league_config.max_players()}/{league_config.max_players()}).", color=0xe74c3c))
                await asyncio.sleep(5); await kanal.delete(); return
            else:
                break

        while True:
            sprzed = clean_tag(await _zadaj_pytanie(kanal, user, "SkrĂłt KLUBU SPRZEDAJÄ„CEGO:", client))
            if not database.get_club(sprzed):
                await kanal.send(embed=discord.Embed(description=f"âťŚ Ten klub nie istnieje!", color=0xe74c3c))
            elif sprzed == kup:
                await kanal.send(embed=discord.Embed(description=f"âťŚ KupujÄ…cy i sprzedajÄ…cy nie mogÄ… byÄ‡ identyczni!", color=0xe74c3c))
            else:
                break

        while True:
            gracz_input = await _zadaj_pytanie(kanal, user, "Oznacz @Zawodnika (lub wpisz imi? je?li brak DC):", client)
            clean_name, player_dc_id, player_label = await resolve_player_identity(guild, gracz_input, client)

            existing = database.is_player_under_contract(clean_name, player_dc_id)
            if not existing:
                await kanal.send(
                    embed=discord.Embed(
                        description=f"❌ **Zawodnik `{clean_name}` nie posiada aktywnego kontraktu!**\n"
                                    "Aby go pozyska? bez klauzuli, u?yj **Podpisania Gracza**.",
                        color=0xe74c3c
                    )
                )
                continue
            if existing.get("club_tag", "").upper() != sprzed:
                actual = existing.get("club_tag", "?")
                await kanal.send(embed=discord.Embed(description=f"? Zawodnik nale?y do `{actual}`, a nie `{sprzed}`!", color=0xe74c3c))
                continue
            real_name = clean_player_name(existing.get("name")) or clean_name
            if not player_dc_id and existing.get("discord_id"):
                player_dc_id = existing.get("discord_id")
                player_label = f"**{real_name}** (<@{player_dc_id}>)"
            break

        while True:
            kwota = await _zadaj_pytanie(kanal, user, "Kwota transferu (np. `10000`):", client)
            if validate_amount_input(kwota): break
            await kanal.send(embed=discord.Embed(description=f"âťŚ Podaj prawidĹ‚owÄ… kwotÄ™.", color=0xe74c3c))

        while True:
            czas = await _zadaj_pytanie(kanal, user, "DĹ‚ugoĹ›Ä‡ nowego kontraktu (np. `60 dni` lub `31.12.2026`):", client)
            wazny_do = parse_expiry_date(czas)
            if wazny_do: break
            await kanal.send(embed=discord.Embed(description=f"âťŚ BĹ‚Ä™dny format daty.", color=0xe74c3c))

        while True:
            klauz = await _zadaj_pytanie(kanal, user, "Nowa Klauzula (np. `15000`) lub `Brak`:", client)
            if validate_amount_input(klauz): break
            await kanal.send(embed=discord.Embed(description=f"âťŚ Podaj prawidĹ‚owÄ… kwotÄ™ lub `Brak`.", color=0xe74c3c))

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

        source_status = "âšˇ Zgoda zbÄ™dna (wykup klauzulowy)" if is_buyout else \
            ("âŹł Oczekuje" if has_source_dc else "â„ąď¸Ź Brak DC zarzÄ…du")

        embed = discord.Embed(
            title=f"{'đź”Ą Wykup Klauzulowy' if is_buyout else 'đź¤ť Transfer'}: {gracz}",
            color=0xe67e22 if is_buyout else 0x9b59b6
        )
        embed.add_field(name="KupujÄ…cy", value=f"`{kup}`", inline=True)
        embed.add_field(name="SprzedajÄ…cy", value=f"`{sprzed}`", inline=True)
        embed.add_field(name="Kwota", value=f"`{kwota}`", inline=True)
        embed.add_field(name="Nowa Klauzula", value=f"`{klauz}`", inline=True)
        embed.add_field(name="Wygasa", value=f"`{wazny_do}`", inline=False)
        embed.add_field(name="Status", value="\n".join([
            f"â€˘ Zawodnik: {'âŹł Oczekuje' if needs_player else 'â„ąď¸Ź Brak DC'}",
            f"â€˘ Klub `{kup}`: {'âŹł Oczekuje' if needs_target else 'â„ąď¸Ź Brak DC zarzÄ…du'}",
            f"â€˘ Klub `{sprzed}`: {source_status}",
            "â€˘ ZarzÄ…d Federacji: âŹł Oczekuje"
        ]), inline=False)

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description=f"âťŚ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2); await kanal.delete(); return

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
                          f"đź“© Klub `{kup}` zĹ‚oĹĽyĹ‚ wniosek o TwĂłj transfer!\nđź”— {thread.jump_url}")

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_transferu] BĹ‚Ä…d: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"âťŚ BĹ‚Ä…d: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await kanal.delete()
        except Exception: pass


# =========================================================================
# 4. WYPOĹ»YCZENIE
# =========================================================================
async def proces_wypozyczenia(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if not database.is_market_open():
        return await interaction.followup.send(
            "â›” **Rynek transferowy jest obecnie ZAMKNIÄTY!**\n"
            "> SkĹ‚adanie wnioskĂłw kontraktowych, transferĂłw i wypoĹĽyczeĹ„ zostaĹ‚o wstrzymane przez ZarzÄ…d Federacji.",
            ephemeral=True
        )
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("âťŚ Masz juĹĽ otwarty kanaĹ‚ wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "wypozyczenie")
    try:
        await interaction.followup.send(f"KanaĹ‚: {kanal.mention}", ephemeral=True)
        await kanal.send("*Masz 15 minut na kaĹĽdÄ… odpowiedĹş.*")

        while True:
            kup = clean_tag(await _zadaj_pytanie(kanal, user, "SkrĂłt KLUBU PRZYJMUJÄ„CEGO (Twojego):", client))
            if not database.get_club(kup):
                await kanal.send(embed=discord.Embed(description=f"âťŚ Klub nie istnieje!", color=0xe74c3c))
            elif not is_club_board_or_owner(user, kup):
                await kanal.send(embed=discord.Embed(description=f"âťŚ Odmowa â€“ nie jesteĹ› w zarzÄ…dzie tego klubu!", color=0xe74c3c))
            elif database.get_club_player_count(kup) >= league_config.max_players():
                await kanal.send(embed=discord.Embed(description=f"âťŚ Klub peĹ‚ny ({league_config.max_players()}/{league_config.max_players()}).", color=0xe74c3c))
                await asyncio.sleep(5); await kanal.delete(); return
            else:
                break

        while True:
            sprzed = clean_tag(await _zadaj_pytanie(kanal, user, "SkrĂłt KLUBU ODDAJÄ„CEGO:", client))
            if not database.get_club(sprzed):
                await kanal.send(embed=discord.Embed(description=f"âťŚ Ten klub nie istnieje!", color=0xe74c3c))
            elif sprzed == kup:
                await kanal.send(embed=discord.Embed(description=f"âťŚ PrzyjmujÄ…cy i oddajÄ…cy nie mogÄ… byÄ‡ identyczni!", color=0xe74c3c))
            else:
                break

        while True:
            gracz_input = await _zadaj_pytanie(kanal, user, "Oznacz @Zawodnika (lub wpisz imi? je?li brak DC):", client)
            clean_name, player_dc_id, player_label = await resolve_player_identity(guild, gracz_input, client)

            existing = database.is_player_under_contract(clean_name, player_dc_id)
            if not existing:
                await kanal.send(
                    embed=discord.Embed(
                        description=f"❌ **Zawodnik `{clean_name}` nie posiada aktywnego kontraktu!**\n"
                                    "Aby go pozyska?, u?yj **Podpisania Gracza**.",
                        color=0xe74c3c
                    )
                )
                continue
            if existing.get("club_tag", "").upper() != sprzed:
                actual = existing.get("club_tag", "?")
                await kanal.send(embed=discord.Embed(description=f"? Zawodnik nale?y do `{actual}`, a nie `{sprzed}`!", color=0xe74c3c))
                continue
            real_name = clean_player_name(existing.get("name")) or clean_name
            if not player_dc_id and existing.get("discord_id"):
                player_dc_id = existing.get("discord_id")
                player_label = f"**{real_name}** (<@{player_dc_id}>)"
            break

        while True:
            czas = await _zadaj_pytanie(kanal, user, "Okres wypoĹĽyczenia (np. `30 dni` lub `15.01.2027`):", client)
            wazny_do = parse_expiry_date(czas)
            if wazny_do: break
            await kanal.send(embed=discord.Embed(description=f"âťŚ BĹ‚Ä™dny format daty.", color=0xe74c3c))

        while True:
            kwota = await _zadaj_pytanie(kanal, user, "OpĹ‚ata za wypoĹĽyczenie (np. `2000`) lub `Brak`:", client)
            if validate_amount_input(kwota): break
            await kanal.send(embed=discord.Embed(description=f"âťŚ Podaj prawidĹ‚owÄ… kwotÄ™ lub `Brak`.", color=0xe74c3c))

        c_target = database.get_club(kup)
        c_source = database.get_club(sprzed)
        has_target_dc = bool(c_target and (c_target.get("board_ids") or c_target.get("reprezentant_dc")))
        has_source_dc = bool(c_source and (c_source.get("board_ids") or c_source.get("reprezentant_dc")))

        embed = discord.Embed(title=f"âŹ±ď¸Ź WypoĹĽyczenie: {gracz}", color=0x1abc9c)
        embed.add_field(name="PrzyjmujÄ…cy", value=f"`{kup}`", inline=True)
        embed.add_field(name="OddajÄ…cy", value=f"`{sprzed}`", inline=True)
        embed.add_field(name="OpĹ‚ata", value=f"`{kwota}`", inline=True)
        embed.add_field(name="Koniec wypoĹĽyczenia", value=f"`{wazny_do}`", inline=False)
        embed.add_field(name="Status", value="\n".join([
            f"â€˘ Zawodnik: {'âŹł Oczekuje' if player_dc_id else 'â„ąď¸Ź Brak DC'}",
            f"â€˘ Klub `{kup}`: {'âŹł Oczekuje' if has_target_dc else 'â„ąď¸Ź Brak DC zarzÄ…du'}",
            f"â€˘ Klub `{sprzed}`: {'âŹł Oczekuje' if has_source_dc else 'â„ąď¸Ź Brak DC zarzÄ…du'}",
            "â€˘ ZarzÄ…d Federacji: âŹł Oczekuje"
        ]), inline=False)

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description=f"âťŚ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2); await kanal.delete(); return

        app_id = database.create_application(
            app_type="WYPOZYCZENIE", applicant_id=user.id,
            player_name=real_name, player_discord_id=player_dc_id,
            target_club=kup, source_club=sprzed,
            amount=kwota, clause="Bez zmian", expires_at=wazny_do,
            needs_player_agree=bool(player_dc_id),
            needs_target_club_agree=has_target_dc, needs_source_club_agree=has_source_dc
        )
        thread = await _send_forum_application(guild, kanal, embed,
                                                f"[{kup}] WypoĹĽyczenie: {gracz}", app_id,
                                                ping_target=kup, ping_source=sprzed)
        if player_dc_id:
            await send_dm(client, player_dc_id,
                          f"đź“© Klub `{kup}` zĹ‚oĹĽyĹ‚ wniosek o Twoje wypoĹĽyczenie!\nđź”— {thread.jump_url}")

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_wypozyczenia] BĹ‚Ä…d: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"âťŚ BĹ‚Ä…d: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await kanal.delete()
        except Exception: pass


# =========================================================================
# 5. ANEKS DO KONTRAKTU
# =========================================================================
async def proces_aneksu(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("âťŚ Masz juĹĽ otwarty kanaĹ‚ wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "aneks")
    try:
        await interaction.followup.send(f"KanaĹ‚: {kanal.mention}", ephemeral=True)
        await kanal.send("*Aneks do kontraktu â€“ masz 15 min na kaĹĽdÄ… odpowiedĹş.*")

        # Weryfikacja: zarzÄ…d musi byÄ‡ w jakimĹ› klubie
        all_clubs = database.get_all_clubs()
        user_club = None
        for c in all_clubs:
            if is_club_board_or_owner(user, c["tag"]):
                user_club = c["tag"]
                break

        if not user_club:
            await kanal.send(embed=discord.Embed(description=f"âťŚ Nie jesteĹ› w zarzÄ…dzie ĹĽadnego zarejestrowanego klubu.", color=0xe74c3c))
            await asyncio.sleep(5); await kanal.delete(); return

        # Zawodnik musi byÄ‡ w tym samym klubie
        while True:
            gracz_input = await _zadaj_pytanie(kanal, user, f"Oznacz @Zawodnika Twojego klubu `{user_club}` (lub wpisz imi?):", client)
            clean_name, player_dc_id, player_label = await resolve_player_identity(guild, gracz_input, client)
            existing = database.is_player_under_contract(clean_name, player_dc_id)
            if not existing:
                await kanal.send(embed=discord.Embed(description=f"? Zawodnik `{clean_name}` nie ma aktywnego kontraktu w bazie!", color=0xe74c3c))
                continue
            if existing.get("club_tag", "").upper() != user_club:
                await kanal.send(embed=discord.Embed(description=f"? Zawodnik nale?y do `{existing.get('club_tag', '?')}`, nie do Twojego klubu `{user_club}`!", color=0xe74c3c))
                continue
            real_name = clean_player_name(existing.get("name")) or clean_name
            if not player_dc_id and existing.get("discord_id"):
                player_dc_id = existing.get("discord_id")
                player_label = f"**{real_name}** (<@{player_dc_id}>)"
            break

        stary_termin = existing.get("expires_at", "?")
        stara_klauzula = existing.get("clause", "Brak")
        await kanal.send(f"â„ąď¸Ź Obecny kontrakt: termin `{stary_termin}` | klauzula `{stara_klauzula}`")

        while True:
            czas = await _zadaj_pytanie(kanal, user, "Nowy termin kontraktu (np. `90 dni` lub `31.12.2027`):", client)
            wazny_do = parse_expiry_date(czas)
            if wazny_do: break
            await kanal.send(embed=discord.Embed(description=f"âťŚ BĹ‚Ä™dny format daty.", color=0xe74c3c))

        while True:
            klauz = await _zadaj_pytanie(kanal, user, "Nowa Klauzula (np. `10000`) lub `Bez zmian` / `Brak`:", client)
            if validate_amount_input(klauz) or klauz.lower() in ("bez zmian",): break
            await kanal.send(embed=discord.Embed(description=f"âťŚ Podaj kwotÄ™ (np. `10000`) lub `Bez zmian`.", color=0xe74c3c))

        final_klauz = stara_klauzula if klauz.lower() == "bez zmian" else klauz

        embed = discord.Embed(title=f"đź“„ Aneks do Kontraktu: {gracz}", color=0x3498db)
        embed.add_field(name="Zawodnik", value=player_label, inline=True)
        embed.add_field(name="Klub", value=f"`{user_club}`", inline=True)
        embed.add_field(name="Stary termin", value=f"`{stary_termin}`", inline=True)
        embed.add_field(name="Nowy termin", value=f"`{wazny_do}`", inline=True)
        embed.add_field(name="Stara klauzula", value=f"`{stara_klauzula}`", inline=True)
        embed.add_field(name="Nowa klauzula", value=f"`{final_klauz}`", inline=True)
        embed.add_field(name="Status", value="\n".join([
            f"â€˘ Zawodnik: {'âŹł Oczekuje' if player_dc_id else 'â„ąď¸Ź Brak DC'}",
            "â€˘ ZarzÄ…d Federacji: âŹł Oczekuje"
        ]), inline=False)

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description=f"âťŚ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2); await kanal.delete(); return

        app_id = database.create_application(
            app_type="ANEKS", applicant_id=user.id,
            player_name=real_name, player_discord_id=player_dc_id,
            target_club=user_club, clause=final_klauz, expires_at=wazny_do,
            needs_player_agree=bool(player_dc_id)
        )
        thread = await _send_forum_application(guild, kanal, embed,
                                                f"[ANEKS] {user_club} â€“ {gracz}", app_id, ping_target=user_club)
        if player_dc_id:
            await send_dm(client, player_dc_id,
                          f"đź“© Klub `{user_club}` zĹ‚oĹĽyĹ‚ wniosek o aneks do Twojego kontraktu!\nđź”— {thread.jump_url}")

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_aneksu] BĹ‚Ä…d: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"âťŚ BĹ‚Ä…d: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await kanal.delete()
        except Exception: pass


# =========================================================================
# 6. ROZWIÄ„ZANIE KONTRAKTU
# =========================================================================
async def proces_rozwiazania(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("âťŚ Masz juĹĽ otwarty kanaĹ‚ wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "rozwiazanie")
    try:
        await interaction.followup.send(f"KanaĹ‚: {kanal.mention}", ephemeral=True)
        await kanal.send("*RozwiÄ…zanie kontraktu â€“ masz 15 min na kaĹĽdÄ… odpowiedĹş.*")

        # Szukaj klubu wnioskodawcy
        all_clubs = database.get_all_clubs()
        user_club = None
        for c in all_clubs:
            if is_club_board_or_owner(user, c["tag"]):
                user_club = c["tag"]
                break
        if not user_club:
            await kanal.send(embed=discord.Embed(description=f"âťŚ Nie jesteĹ› w zarzÄ…dzie ĹĽadnego zarejestrowanego klubu.", color=0xe74c3c))
            await asyncio.sleep(5); await kanal.delete(); return

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

        while True:
            tryb = await _zadaj_pytanie(
                kanal, user,
                "Wybierz tryb:\n`1` â€“ Za porozumieniem stron\n`2` â€“ Dyscyplinarne (np. brak kontaktu, niesubordynacja)",
                client
            )
            if tryb in ("1", "2"): break
            await kanal.send(embed=discord.Embed(description=f"âťŚ Wpisz `1` lub `2`.", color=0xe74c3c))

        uzasadnienie = await _zadaj_pytanie(kanal, user, "Podaj krĂłtkie uzasadnienie rozwiÄ…zania:", client)

        app_type = "ROZWIAZANIE_POLUBOWNE" if tryb == "1" else "ROZWIAZANIE_DYSCYPLINARNE"
        needs_player = bool(player_dc_id) and tryb == "1"  # Zgoda gracza tylko przy porozumieniu

        embed = discord.Embed(
            title=f"{'đź¤ť Porozumienie stron' if tryb == '1' else 'âš–ď¸Ź Wniosek dyscyplinarny'}: {gracz}",
            color=0xe67e22
        )
        embed.add_field(name="Zawodnik", value=player_label, inline=True)
        embed.add_field(name="Klub", value=f"`{user_club}`", inline=True)
        embed.add_field(name="Tryb", value="Za porozumieniem stron" if tryb == "1" else "Dyscyplinarne", inline=True)
        embed.add_field(name="Uzasadnienie", value=uzasadnienie, inline=False)
        embed.add_field(name="Status", value="\n".join([
            f"â€˘ Zawodnik: {'âŹł Oczekuje zgody' if needs_player else ('â„ąď¸Ź Brak DC' if not player_dc_id else 'đź”” BÄ™dzie powiadomiony')}",
            "â€˘ ZarzÄ…d Federacji: âŹł Oczekuje na ostatecznÄ… decyzjÄ™"
        ]), inline=False)

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description=f"âťŚ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2); await kanal.delete(); return

        app_id = database.create_application(
            app_type=app_type, applicant_id=user.id,
            player_name=real_name, player_discord_id=player_dc_id,
            source_club=user_club, reason=uzasadnienie,
            needs_player_agree=needs_player
        )
        thread = await _send_forum_application(guild, kanal, embed,
                                                f"[ROZWIÄ„ZANIE] {user_club} â€“ {gracz}", app_id)
        if player_dc_id:
            msg = (f"đź“© Klub `{user_club}` zĹ‚oĹĽyĹ‚ wniosek o {'rozwiÄ…zanie kontraktu za porozumieniem stron' if tryb == '1' else 'dyscyplinarne rozwiÄ…zanie umowy'}.\n"
                   f"đź”— {thread.jump_url}")
            await send_dm(client, player_dc_id, msg)

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_rozwiazania] BĹ‚Ä…d: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"âťŚ BĹ‚Ä…d: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await kanal.delete()
        except Exception: pass


# =========================================================================
# 7. ZARZÄ„DZANIE KLUBEM (Nazwa, TAG, WĹ‚aĹ›ciciel, ZarzÄ…d)
# =========================================================================
async def proces_zarzadzania_klubem(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("âťŚ Masz juĹĽ otwarty kanaĹ‚ wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "zarzadzanie")
    try:
        await interaction.followup.send(f"KanaĹ‚: {kanal.mention}", ephemeral=True)
        embed_start = discord.Embed(title="âš™ď¸Ź ZarzÄ…dzanie Klubem", description=f"Witaj {user.mention}! Bot poprowadzi CiÄ™ przez proces.\n> Masz **15 minut** na kaĹĽdÄ… odpowiedĹş.", color=0x2b2d31)
        embed_start.set_footer(text=f"{league_config.league_name()} • Biuro")
        await kanal.send(embed=embed_start)

        # Weryfikacja: wnioskodawca musi byÄ‡ w zarzÄ…dzie lub wĹ‚aĹ›cicielem
        all_clubs = database.get_all_clubs()
        user_club = None
        for c in all_clubs:
            if is_club_board_or_owner(user, c["tag"]):
                user_club = c["tag"]
                break
        if not user_club:
            await kanal.send(embed=discord.Embed(description=f"âťŚ Nie jesteĹ› w zarzÄ…dzie ani wĹ‚aĹ›cicielem ĹĽadnego zarejestrowanego klubu.", color=0xe74c3c))
            await asyncio.sleep(5); await kanal.delete(); return

        stary_klub = database.get_club(user_club)
        stara_nazwa = stary_klub.get("name", user_club)
        stary_wlasciciel = stary_klub.get("founder_txt") or "Brak"
        stary_zarzad = stary_klub.get("board_txt") or "Brak"

        await kanal.send(
            f"â„ąď¸Ź **Aktualne dane klubu:**\n"
            f"> PeĹ‚na nazwa: **{stara_nazwa}**\n"
            f"> TAG: `{user_club}`\n"
            f"> WĹ‚aĹ›ciciel: {stary_wlasciciel}\n"
            f"> ZarzÄ…d: {stary_zarzad}"
        )

        # 1. PeĹ‚na nazwa
        nowa_nazwa_input = await _zadaj_pytanie(kanal, user, f"Nowa peĹ‚na nazwa klubu (lub `Bez zmian` by zachowaÄ‡ `{stara_nazwa}`):", client)
        nowa_nazwa = stara_nazwa if nowa_nazwa_input.lower() == "bez zmian" else nowa_nazwa_input.strip()

        # 2. TAG
        while True:
            nowy_tag_input = await _zadaj_pytanie(kanal, user, f"Nowy 3-literowy TAG (lub `Bez zmian` by zachowaÄ‡ `{user_club}`):", client)
            if nowy_tag_input.lower() == "bez zmian":
                nowy_tag = user_club
                break
            nowy_tag = clean_tag(nowy_tag_input)
            if not is_valid_tag(nowy_tag):
                await kanal.send(embed=discord.Embed(description=f"âťŚ TAG musi skĹ‚adaÄ‡ siÄ™ dokĹ‚adnie z 3 liter lub cyfr (np. FCZ, LG2)!", color=0xe74c3c))
                continue
            if nowy_tag != user_club and database.get_club(nowy_tag):
                await kanal.send(embed=discord.Embed(description=f"âťŚ TAG `{nowy_tag}` jest juĹĽ zajÄ™ty przez inny klub!", color=0xe74c3c))
                continue
            break

        # 3. WĹ‚aĹ›ciciel
        nowy_wlasciciel_input = await _zadaj_pytanie(kanal, user, "Nowy WĹ‚aĹ›ciciel klubu (oznacz @WĹ‚aĹ›ciciel lub `Bez zmian`):", client)
        nowy_wlasciciel = stary_wlasciciel if nowy_wlasciciel_input.lower() == "bez zmian" else nowy_wlasciciel_input.strip()

        # 4. ZarzÄ…d
        nowy_zarzad_input = await _zadaj_pytanie(kanal, user, "Nowy ZarzÄ…d klubu (oznacz @ZarzÄ…d, wpisz `Brak` lub `Bez zmian`):", client)
        nowy_zarzad = stary_zarzad if nowy_zarzad_input.lower() == "bez zmian" else nowy_zarzad_input.strip()

        # Weryfikacja: czy cokolwiek siÄ™ zmieniĹ‚o?
        if (nowy_tag == user_club and nowa_nazwa == stara_nazwa and
            nowy_wlasciciel == stary_wlasciciel and nowy_zarzad == stary_zarzad):
            await kanal.send(embed=discord.Embed(description=f"âťŚ Nie wprowadzono ĹĽadnych zmian w danych klubu. Anulowanie.", color=0xe74c3c))
            await asyncio.sleep(3); await kanal.delete(); return

        # 5. PowĂłd
        powod = await _zadaj_pytanie(kanal, user, "Podaj powĂłd wprowadzanych zmian:", client)

        embed = discord.Embed(title="âš™ď¸Ź Wniosek o AktualizacjÄ™ Klubu", color=0x9b59b6)
        embed.add_field(name="Klub", value=f"`{user_club}`" if nowy_tag == user_club else f"`{user_club}` âž” `{nowy_tag}`", inline=True)
        embed.add_field(name="Nazwa", value=nowa_nazwa if nowa_nazwa == stara_nazwa else f"~~{stara_nazwa}~~ âž” **{nowa_nazwa}**", inline=True)
        embed.add_field(name="WĹ‚aĹ›ciciel", value=nowy_wlasciciel if nowy_wlasciciel == stary_wlasciciel else f"{nowy_wlasciciel} *(Nowy)*", inline=False)
        embed.add_field(name="ZarzÄ…d", value=nowy_zarzad if nowy_zarzad == stary_zarzad else f"{nowy_zarzad} *(Nowy)*", inline=False)
        embed.add_field(name="PowĂłd", value=powod, inline=False)
        embed.add_field(name="Status", value="âŹł Oczekuje na decyzjÄ™ ZarzÄ…du Federacji", inline=False)

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description=f"âťŚ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2); await kanal.delete(); return

        app_id = database.create_application(
            app_type="ZARZADZANIE_KLUBU", applicant_id=user.id,
            club_name=nowa_nazwa, club_tag=nowy_tag, old_club_tag=user_club,
            founder_txt=stary_wlasciciel, board_txt=stary_zarzad,
            new_founder_txt=nowy_wlasciciel, new_board_txt=nowy_zarzad,
            reason=powod
        )
        tag_display = f"{user_club} âž” {nowy_tag}" if nowy_tag != user_club else user_club
        await _send_forum_application(guild, kanal, embed,
                                       f"[ZARZÄ„DZANIE] {tag_display} â€“ {nowa_nazwa}", app_id)

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_zarzadzania_klubem] BĹ‚Ä…d: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"âťŚ BĹ‚Ä…d: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await kanal.delete()
        except Exception: pass

proces_rebrandingu = proces_zarzadzania_klubem

