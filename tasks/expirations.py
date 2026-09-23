from datetime import datetime, timedelta
import discord
from discord.ext import tasks
import database
from config import CHANNEL_KOMUNIKATY_ID
from utils.helpers import send_dm, get_now_warsaw, get_or_fetch_member, get_komunikaty_channel, format_schedule_discord

def setup_expirations_task(bot: discord.Client, guild_id: int = None):

    @tasks.loop(seconds=30)
    async def check_expirations():
        await bot.wait_until_ready()

        if guild_id:
            guild = bot.get_guild(guild_id)
        else:
            guild = bot.guilds[0] if bot.guilds else None

        if not guild:
            print("[Expirations] Nie znaleziono serwera. Sprawdź GUILD_ID w config.")
            return

        kom_channel = await get_komunikaty_channel(bot, guild)
        now = get_now_warsaw()

        # ── 0. Harmonogram Otwarcia / Zamknięcia Rynku Transferowego ──
        try:
            market_state = database.get_market_state()
            close_at_str = market_state.get("close_at")
            open_at_str = market_state.get("open_at")

            # Sprawdzenie planowanego zamknięcia rynku (gdy wybije wyznaczona godzina i data)
            if close_at_str:
                try:
                    close_dt = datetime.strptime(close_at_str, "%Y-%m-%d %H:%M:%S")
                    if now >= close_dt:
                        database.set_market_status("CLOSED", scheduled_close="")
                        print(f"[Market] Wybiła wyznaczona godzina zamknięcia rynku ({close_at_str}). Rynek ZAMKNIĘTY.")
                        if kom_channel:
                            await kom_channel.send(
                                "🔒 **RYNEK TRANSFEROWY ZOSTAŁ ZAMKNIĘTY!**\n"
                                f"> Wybiła zaplanowana data i godzina zamknięcia okienka ({format_schedule_discord(close_at_str)}).\n"
                                "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało oficjalnie **zablokowane**.",
                                allowed_mentions=discord.AllowedMentions.none()
                            )
                except ValueError:
                    pass

            # Sprawdzenie planowanego otwarcia rynku (gdy wybije wyznaczona godzina i data)
            if open_at_str:
                try:
                    open_dt = datetime.strptime(open_at_str, "%Y-%m-%d %H:%M:%S")
                    if now >= open_dt:
                        database.set_market_status("OPEN", scheduled_open="")
                        print(f"[Market] Wybiła wyznaczona godzina otwarcia rynku ({open_at_str}). Rynek OTWARTY.")
                        if kom_channel:
                            await kom_channel.send(
                                "🔓 **RYNEK TRANSFEROWY ZOSTAŁ OTWARTY!**\n"
                                f"> Wybiła zaplanowana data i godzina otwarcia okienka ({format_schedule_discord(open_at_str)})!\n"
                                "> Kluby mogą oficjalnie rejestrować wolnych agentów, realizować transfery i wypożyczenia!",
                                allowed_mentions=discord.AllowedMentions.none()
                            )
                except ValueError:
                    pass
        except Exception as e:
            print(f"[Expirations] Błąd sprawdzania harmonogramu rynku: {e}")

        players = database.get_all_players()

        # ── 1. Sprawdzanie wygaśnięć kontraktów i przypomnień per gracz ──
        for player in players:
            try:
                expires_at_str = player.get("expires_at")
                if not expires_at_str:
                    continue

                try:
                    expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue

                gracz_name = player.get("name")
                typ = player.get("contract_type")
                klub_obecny = player.get("club_tag")
                klub_macierzysty = player.get("parent_club_tag") or klub_obecny
                dc_id = player.get("discord_id")
                c_obecny = database.get_club(klub_obecny)
                c_macierz = database.get_club(klub_macierzysty)
                rep_id = c_obecny.get("reprezentant_dc") if c_obecny else None

                dni_do_konca = (expires_at - now).total_seconds() / 86400.0

                # ── Przypomnienia o zbliżającym się końcu umowy (oparte na flagach w SQLite) ──
                gracz_mention = f"<@{dc_id}>" if dc_id else f"**{gracz_name}**"
                klub_nazwa = c_obecny.get("name", klub_obecny) if c_obecny else klub_obecny

                # ── OSTRZEŻENIA (1-7 DNI DO KOŃCA) ORAZ BLOK TRY-EXCEPT DM ──
                # 7 dni przed wygaśnięciem
                if dni_do_konca <= 7.0 and dni_do_konca > 3.0 and not player.get("warned_7d"):
                    msg = (
                        f"⚠️ **Uwaga! Za ok. 7 dni kończy się kontrakt gracza {gracz_mention} "
                        f"w klubie **{klub_nazwa}** (`{klub_obecny}`)!**\n"
                        f"> Przedłuż umowę wnioskiem (Aneks), aby gracz nie stał się wolnym agentem.\n"
                        f"> Termin wygaśnięcia: `{expires_at_str}`"
                    )
                    try: await _send_warning(bot, dc_id, rep_id, msg)
                    except Exception as e: print(f"Błąd DM do {gracz_name}: {e}")
                    database.set_player_warning_flag(gracz_name, "warned_7d")

                # 3 dni przed wygaśnięciem
                elif dni_do_konca <= 3.0 and dni_do_konca > 1.0 and not player.get("warned_3d"):
                    msg = (
                        f"⚠️ **Zostały 3 dni!** Kontrakt gracza {gracz_mention} "
                        f"w klubie **{klub_nazwa}** (`{klub_obecny}`) wygasa niedługo!\n"
                        f"> Termin wygaśnięcia: `{expires_at_str}`"
                    )
                    try: await _send_warning(bot, dc_id, rep_id, msg)
                    except Exception as e: print(f"Błąd DM do {gracz_name}: {e}")
                    database.set_player_warning_flag(gracz_name, "warned_3d")

                # 1 dzień przed wygaśnięciem
                elif dni_do_konca <= 1.0 and dni_do_konca > 0.0 and not player.get("warned_1d"):
                    msg = (
                        f"🚨 **OSTATNI DZIEŃ!** Kontrakt gracza {gracz_mention} "
                        f"w klubie **{klub_nazwa}** (`{klub_obecny}`) wygasa jutro!\n"
                        f"> Termin wygaśnięcia: `{expires_at_str}`"
                    )
                    try: await _send_warning(bot, dc_id, rep_id, msg)
                    except Exception as e: print(f"Błąd DM do {gracz_name}: {e}")
                    database.set_player_warning_flag(gracz_name, "warned_1d")

                # ── SPRAWDZANIE ZASADY 4. ZAWODNIKA (IS_OVERFLOW) ──
                if player.get("is_overflow") == 1 and player.get("slot_deadline"):
                    try:
                        deadline_dt = datetime.strptime(player.get("slot_deadline"), "%Y-%m-%d %H:%M:%S")
                        if now >= deadline_dt:
                            member = await get_or_fetch_member(guild, dc_id) if dc_id else None
                            if member and c_obecny:
                                r_zaw = guild.get_role(c_obecny.get("role_player_id", 0))
                                if r_zaw:
                                    try: await member.remove_roles(r_zaw)
                                    except Exception as e: print(f"[Expirations] Błąd usunięcia roli overflow: {e}")
                            
                            database.delete_player(gracz_name)
                            if dc_id:
                                # Wyrzucenie do bazy rezerwowej
                                database.register_free_agent(dc_id, gracz_name, "UNI", "ALL")
                            
                            database.add_transfer_history(
                                player_name=gracz_name, player_discord_id=dc_id,
                                from_club=klub_obecny, to_club=None,
                                transfer_type="PRZEKROCZENIE_LIMITU_REZERWA", amount=None
                            )
                            
                            if kom_channel:
                                await kom_channel.send(
                                    f"🚨 **KARA ZA PRZEKROCZENIE LIMITU!**\n"
                                    f"> Klub **{klub_nazwa}** (`{klub_obecny}`) nie zwolnił miejsca w kadrze w ciągu 5 dni.\n"
                                    f"> Zawodnik **{gracz_name}** został odebrany i przeniesiony do **Bazy Rezerwowej** (utrata statusu transferowego).",
                                    allowed_mentions=discord.AllowedMentions.none()
                                )
                            continue  # Gracz wyrzucony, nie przetwarzaj dalej kontraktu
                    except ValueError:
                        pass

                # ── Wygaśnięcie umowy ──
                if now >= expires_at:
                    member = await get_or_fetch_member(guild, dc_id) if dc_id else None

                    # ── WYPOŻYCZENIE: powrót do klubu macierzystego ──
                    if typ == "WYPOZYCZENIE":
                        if member:
                            if c_obecny:
                                r_temp = guild.get_role(c_obecny.get("role_player_id", 0))
                                if r_temp:
                                    try: await member.remove_roles(r_temp)
                                    except Exception as e: print(f"[Expirations] Błąd usunięcia roli: {e}")
                            if c_macierz:
                                r_mac = guild.get_role(c_macierz.get("role_player_id", 0))
                                if r_mac:
                                    try: await member.add_roles(r_mac)
                                    except Exception as e: print(f"[Expirations] Błąd nadania roli macierzystej: {e}")

                        # Przywrócenie oryginalnego kontraktu i klauzuli macierzystej
                        parent_expires = player.get("parent_contract_expires_at")
                        restored_clause = player.get("parent_clause") or "Brak"

                        database.add_or_update_player(
                            name=gracz_name, discord_id=dc_id,
                            club_tag=klub_macierzysty, parent_club_tag=klub_macierzysty,
                            clause=restored_clause,
                            contract_type="TRANSFER",
                            expires_at=parent_expires,
                            parent_contract_expires_at=None,
                            parent_clause=None
                        )
                        database.add_transfer_history(
                            player_name=gracz_name, player_discord_id=dc_id,
                            from_club=klub_obecny, to_club=klub_macierzysty,
                            transfer_type="POWROT_Z_WYPOZYCZENIA", amount=None
                        )

                        if kom_channel:
                            nazwa_obecny = c_obecny.get("name", klub_obecny) if c_obecny else klub_obecny
                            nazwa_macierz = c_macierz.get("name", klub_macierzysty) if c_macierz else klub_macierzysty
                            await kom_channel.send(
                                f"⏱️ **KONIEC WYPOŻYCZENIA!**\n"
                                f"> Zawodnik **{gracz_name}** wraca z **{nazwa_obecny}** "
                                f"do macierzystego klubu **{nazwa_macierz}** (`{klub_macierzysty}`)!",
                                allowed_mentions=discord.AllowedMentions.none()
                            )

                        if dc_id:
                            await send_dm(
                                bot, dc_id,
                                f"⏱️ **Twoje wypożyczenie w `{klub_obecny}` wygasło.**\n"
                                f"Wróciłeś do macierzystego klubu `{klub_macierzysty}`."
                            )

                    # ── KONTRAKT ZWYKŁY: wygaśnięcie – wolny agent ──
                    else:
                        if member and c_obecny:
                            r_zaw = guild.get_role(c_obecny.get("role_player_id", 0))
                            if r_zaw:
                                try: await member.remove_roles(r_zaw)
                                except Exception as e: print(f"[Expirations] Błąd usunięcia roli przy wygaśnięciu: {e}")

                        database.delete_player(gracz_name)
                        database.add_transfer_history(
                            player_name=gracz_name, player_discord_id=dc_id,
                            from_club=klub_obecny, to_club=None,
                            transfer_type="WYGASNIECIE", amount=None
                        )

                        if kom_channel:
                            nazwa_klub = c_obecny.get("name", klub_obecny) if c_obecny else klub_obecny
                            await kom_channel.send(
                                f"📢 **WYGAŚNIĘCIE KONTRAKTU!**\n"
                                f"> Kontrakt zawodnika **{gracz_name}** z drużyną **{nazwa_klub}** "
                                f"(`{klub_obecny}`) dobiegł końca.\n"
                                f"> Zawodnik staje się wolnym agentem!",
                                allowed_mentions=discord.AllowedMentions.none()
                            )

                        if dc_id:
                            await send_dm(
                                bot, dc_id,
                                f"📢 **Twój kontrakt z klubem `{klub_obecny}` wygasł.**\n"
                                f"Jesteś teraz wolnym agentem! Kliknij przycisk **Szukam Klubu** "
                                f"w panelu rynku transferowego, jeśli szukasz nowego klubu."
                            )

            except Exception as e:
                print(f"[Expirations] Błąd przetwarzania gracza {player.get('name')}: {e}")

        # ── 2. Czyszczenie nieaktywnych ogłoszeń na Giełdzie Wolnych Agentów (po 14 dniach) ──
        try:
            removed = database.cleanup_expired_free_agents(days=14)
            for fa in removed:
                dc_id = fa.get("discord_id")
                if dc_id:
                    await send_dm(
                        bot, dc_id,
                        "ℹ️ Twoje ogłoszenie na Giełdzie Wolnych Agentów wygasło z powodu braku odświeżenia przez 14 dni.\n"
                        "Jeśli nadal szukasz klubu, kliknij przycisk **Szukam Klubu** na rynku transferowym."
                    )
        except Exception as e:
            print(f"[Expirations] Błąd czyszczenia giełdy: {e}")

    @check_expirations.error
    async def on_expiration_error(error):
        print(f"[CRITICAL] Błąd w pętli check_expirations: {error}")

    return check_expirations


async def _send_warning(bot: discord.Client, player_dc_id: int, rep_dc_id: int, message: str):
    """Wysyła ostrzeżenie DM do gracza i reprezentanta klubu."""
    if player_dc_id:
        await send_dm(bot, player_dc_id, message)
    if rep_dc_id and rep_dc_id != player_dc_id:
        await send_dm(bot, rep_dc_id, message)
