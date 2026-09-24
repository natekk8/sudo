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


async def proces_zarzadzania_klubem(interaction: discord.Interaction):
    guild, user, client = interaction.guild, interaction.user, interaction.client
    if _check_spam(guild, user, interaction):
        return await interaction.followup.send("❌ Masz już otwarty kanał wniosku.", ephemeral=True)

    kanal = await _create_ticket_channel(guild, user, "zarzadzanie")
    try:
        await interaction.followup.send(f"Kanał: {kanal.mention}", ephemeral=True)
        embed_start = discord.Embed(
            title="⚙️ Zarządzanie Klubem",
            description=f"Witaj {user.mention}! Bot poprowadzi Cię przez proces aktualizacji danych klubu.\n> Masz **15 minut** na każdą odpowiedź.",
            color=0x2b2d31
        )
        embed_start.set_footer(text=f"{league_config.league_name()} • Biuro")
        await kanal.send(embed=embed_start)

        all_clubs = database.get_all_clubs()
        if not all_clubs:
            await kanal.send(embed=discord.Embed(description="❌ W bazie danych nie ma obecnie żadnych zarejestrowanych klubów.", color=0xe74c3c))
            await asyncio.sleep(5); await _safe_delete_channel(kanal); return

        is_fed = is_federation(user) or (getattr(user, "guild_permissions", None) and user.guild_permissions.administrator)

        user_club = None
        stary_klub = None

        if is_fed:
            # Zarząd Federacji / Admin może zarządzać dowolnym klubem
            club_list_str = "\n".join([f"> • `{c['tag']}` — **{c.get('name', c['tag'])}**" for c in all_clubs[:20]])
            if len(all_clubs) > 20:
                club_list_str += f"\n> *...i {len(all_clubs) - 20} innych klubów*"

            embed_fed_select = discord.Embed(
                title="🏛️ Panel Federacji — Wybór Klubu",
                description=(
                    f"Jako **Zarząd Federacji / Administrator** masz uprawnienia do zarządzania dowolnym klubem.\n\n"
                    f"**Zarejestrowane kluby ({len(all_clubs)}):**\n{club_list_str}\n\n"
                    f"Podaj **TAG** klubu, którym chcesz zarządzać (lub wpisz `Anuluj`):"
                ),
                color=0x3498db
            )
            await kanal.send(embed=embed_fed_select)

            while True:
                fed_tag_in = await _zadaj_pytanie(kanal, user, "Podaj TAG klubu:", client)
                if fed_tag_in.strip().lower() == "anuluj":
                    await kanal.send(embed=discord.Embed(description="❌ Anulowano.", color=0x95a5a6))
                    await asyncio.sleep(2); await _safe_delete_channel(kanal); return
                t_clean = clean_tag(fed_tag_in)
                matched = database.get_club(t_clean)
                if matched:
                    user_club = t_clean
                    stary_klub = matched
                    break
                await kanal.send(embed=discord.Embed(description=f"❌ Klub o tagu `{t_clean}` nie istnieje w bazie!", color=0xe74c3c))
        else:
            # Zwykły użytkownik - sprawdzamy kluby, którymi zarządza
            user_clubs = [c for c in all_clubs if is_club_board_or_owner(user, c["tag"])]
            if not user_clubs:
                await kanal.send(embed=discord.Embed(description="❌ Nie jesteś w zarządzie ani właścicielem żadnego zarejestrowanego klubu.", color=0xe74c3c))
                await asyncio.sleep(5); await _safe_delete_channel(kanal); return

            if len(user_clubs) == 1:
                user_club = user_clubs[0]["tag"]
                stary_klub = user_clubs[0]
            else:
                c_list = "\n".join([f"> • `{c['tag']}` — **{c.get('name', c['tag'])}**" for c in user_clubs])
                embed_multi = discord.Embed(
                    title="🏛️ Wybierz swój klub",
                    description=f"Jesteś przypisany do kilku klubów:\n{c_list}\n\nWpisz **TAG** klubu, którym chcesz zarządzać:",
                    color=0x3498db
                )
                await kanal.send(embed=embed_multi)
                while True:
                    tag_in = await _zadaj_pytanie(kanal, user, "Wpisz TAG klubu (lub `Anuluj`):", client)
                    if tag_in.strip().lower() == "anuluj":
                        await kanal.send(embed=discord.Embed(description="❌ Anulowano.", color=0x95a5a6))
                        await asyncio.sleep(2); await _safe_delete_channel(kanal); return
                    t_clean = clean_tag(tag_in)
                    matched = [c for c in user_clubs if c["tag"] == t_clean]
                    if matched:
                        user_club = t_clean
                        stary_klub = matched[0]
                        break
                    await kanal.send(embed=discord.Embed(description=f"❌ Nie zarządzasz klubem o tagu `{t_clean}`.", color=0xe74c3c))

        stara_nazwa = stary_klub.get("name", user_club)
        stary_wlasciciel = stary_klub.get("founder_txt") or "Brak"
        stary_zarzad = stary_klub.get("board_txt") or "Brak"

        await kanal.send(
            f"ℹ️ **Aktualne dane klubu:**\n"
            f"> Pełna nazwa: **{stara_nazwa}**\n"
            f"> TAG: `{user_club}`\n"
            f"> Właściciel: {stary_wlasciciel}\n"
            f"> Zarząd: {stary_zarzad}"
        )

        # Wybór akcji: 1. Edycja danych, 2. Usunięcie klubu
        embed_action = discord.Embed(
            title="⚙️ Wybierz Akcję Zarządzania",
            description=(
                f"Zarządzasz klubem **{stara_nazwa}** (`{user_club}`). Co chcesz zrobić?\n\n"
                "> `1` • **Edycja danych klubu** (Nazwa, TAG, Właściciel, Zarząd)\n"
                "> `2` • **Usunięcie / Likwidacja klubu** (Wykreślenie z ligi i rozwiązanie umów graczy)\n\n"
                "Wpisz `1`, `2` lub `Anuluj`:"
            ),
            color=0x3498db
        )
        await kanal.send(embed=embed_action)

        action_choice = None
        while True:
            choice_in = await _zadaj_pytanie(kanal, user, "Wybierz opcję (1 lub 2):", client)
            ch = choice_in.strip().lower()
            if ch == "anuluj":
                await kanal.send(embed=discord.Embed(description="❌ Anulowano.", color=0x95a5a6))
                await asyncio.sleep(2); await _safe_delete_channel(kanal); return
            if ch in ("1", "2"):
                action_choice = ch
                break
            await kanal.send(embed=discord.Embed(description="❌ Wpisz `1` (Edycja) lub `2` (Usunięcie)!", color=0xe74c3c))

        # ── OPCJA 2: LIKWIDACJA KLUBU ──
        if action_choice == "2":
            embed_del_warn = discord.Embed(
                title="⚠️ Likwidacja Klubu — Ostrzeżenie",
                description=(
                    f"Zamierzasz zlikwidować klub **{stara_nazwa}** (`{user_club}`).\n\n"
                    f"> • Wszyscy zawodnicy tego klubu zostaną **zwolnieni z kontraktów**.\n"
                    f"> • Klub zostanie **wykreślony** z bazy ligi.\n"
                    f"> • Role klubowe zostaną usunięte z serwera Discord.\n\n"
                    f"Aby potwierdzić, wpisz dokładnie: **POTWIERDZAM**\n"
                    f"*(Wpisanie czegokolwiek innego anuluje proces)*"
                ),
                color=0xe74c3c
            )
            await kanal.send(embed=embed_del_warn)
            confirm_input = await _zadaj_pytanie(kanal, user, "Wpisz POTWIERDZAM lub Anuluj:", client)
            if confirm_input.strip().upper() != "POTWIERDZAM":
                await kanal.send(embed=discord.Embed(description="❌ Likwidacja klubu została anulowana.", color=0x95a5a6))
                await asyncio.sleep(2); await _safe_delete_channel(kanal); return

            powod_del = await _zadaj_pytanie(kanal, user, "Podaj powód likwidacji klubu:", client)

            if is_fed:
                # Federacja / Admin likwiduje klub natychmiastowo
                r_b_id = stary_klub.get("role_board_id", 0)
                r_p_id = stary_klub.get("role_player_id", 0)
                if r_b_id:
                    r_b = guild.get_role(r_b_id)
                    if r_b:
                        try: await r_b.delete(reason=f"Likwidacja klubu {user_club} przez Federację")
                        except Exception as e: print(f"[Zarządzanie] Błąd usuwania roli zarządu: {e}")
                if r_p_id:
                    r_p = guild.get_role(r_p_id)
                    if r_p:
                        try: await r_p.delete(reason=f"Likwidacja klubu {user_club} przez Federację")
                        except Exception as e: print(f"[Zarządzanie] Błąd usuwania roli gracza: {e}")

                database.delete_club(user_club, terminate_players=True)

                kom_channel = await get_komunikaty_channel(client, guild)
                if kom_channel:
                    try:
                        embed_ann = discord.Embed(
                            title="🏛️ Likwidacja Klubu (FSS)",
                            description=f"Klub **{stara_nazwa}** (`{user_club}`) został oficjalnie zlikwidowany i wykreślony z rozgrywek Federacji Siatkówki Stołowej.",
                            color=0xe74c3c
                        )
                        embed_ann.add_field(name="Decyzja", value=f"Podjęta przez Zarząd Federacji ({user.mention})", inline=False)
                        embed_ann.add_field(name="Powód", value=powod_del, inline=False)
                        embed_ann.set_footer(text=f"{league_config.league_name()} • Oficjalny Komunikat")
                        await kom_channel.send(embed=embed_ann)
                    except Exception as e:
                        print(f"[Zarządzanie] Błąd komunikatu likwidacji: {e}")

                await kanal.send(embed=discord.Embed(
                    title="✅ Klub Zlikwidowany",
                    description=f"Klub **{stara_nazwa}** (`{user_club}`) został pomyślnie zlikwidowany, a kontrakty graczy rozwiązane.",
                    color=0x2ecc71
                ))
                await asyncio.sleep(4); await _safe_delete_channel(kanal); return
            else:
                # Właściciel składa wniosek na forum
                embed_del_app = discord.Embed(title=f"🗑️ Wniosek o Likwidację: {user_club}", color=0xe74c3c)
                embed_del_app.add_field(name="Klub", value=f"`{user_club}` – **{stara_nazwa}**", inline=False)
                embed_del_app.add_field(name="Wnioskodawca", value=user.mention, inline=True)
                embed_del_app.add_field(name="Powód", value=powod_del, inline=False)
                embed_del_app.add_field(name="Status", value="⏳ Oczekuje na decyzję Zarządu Federacji", inline=False)
                embed_del_app.set_footer(text=f"{league_config.league_name()} • Biuro")

                v = WniosekConfirmView(user.id)
                await kanal.send(embed=embed_del_app, view=v)
                await v.wait()
                if not v.value:
                    await kanal.send(embed=discord.Embed(description="❌ Wniosek anulowany.", color=0xe74c3c))
                    await asyncio.sleep(2); await _safe_delete_channel(kanal); return

                app_id = database.create_application(
                    app_type="USUNIECIE_KLUBU", applicant_id=user.id,
                    club_name=stara_nazwa, club_tag=user_club, old_club_tag=user_club,
                    reason=powod_del
                )
                await _send_forum_application(guild, kanal, embed_del_app,
                                               f"[USUNIĘCIE] {user_club} – {stara_nazwa}", app_id)
                return

        # ── OPCJA 1: EDYCJA DANYCH KLUBU ──
        # 1. Pełna nazwa
        nowa_nazwa_input = await _zadaj_pytanie(kanal, user, f"Nowa pełna nazwa klubu (lub `Bez zmian` by zachować `{stara_nazwa}`):", client)
        nowa_nazwa = stara_nazwa if nowa_nazwa_input.lower() == "bez zmian" else nowa_nazwa_input.strip()

        # 2. TAG
        while True:
            nowy_tag_input = await _zadaj_pytanie(kanal, user, f"Nowy 3-literowy TAG (lub `Bez zmian` by zachować `{user_club}`):", client)
            if nowy_tag_input.lower() == "bez zmian":
                nowy_tag = user_club
                break
            nowy_tag = clean_tag(nowy_tag_input)
            if not is_valid_tag(nowy_tag):
                await kanal.send(embed=discord.Embed(description="❌ TAG musi składać się dokładnie z 3 liter lub cyfr (np. FCZ, LG2)!", color=0xe74c3c))
                continue
            if nowy_tag != user_club and database.get_club(nowy_tag):
                await kanal.send(embed=discord.Embed(description=f"❌ TAG `{nowy_tag}` jest już zajęty przez inny klub!", color=0xe74c3c))
                continue
            break

        # 3. Właściciel
        nowy_wlasciciel_input = await _zadaj_pytanie(kanal, user, "Nowy Właściciel klubu (oznacz @Właściciel lub `Bez zmian`):", client)
        nowy_wlasciciel = stary_wlasciciel if nowy_wlasciciel_input.lower() == "bez zmian" else nowy_wlasciciel_input.strip()

        # 4. Zarząd
        nowy_zarzad_input = await _zadaj_pytanie(kanal, user, "Nowy Zarząd klubu (oznacz @Zarząd, wpisz `Brak` lub `Bez zmian`):", client)
        nowy_zarzad = stary_zarzad if nowy_zarzad_input.lower() == "bez zmian" else nowy_zarzad_input.strip()

        # Weryfikacja: czy cokolwiek się zmieniło?
        if (nowy_tag == user_club and nowa_nazwa == stara_nazwa and
            nowy_wlasciciel == stary_wlasciciel and nowy_zarzad == stary_zarzad):
            await kanal.send(embed=discord.Embed(description="❌ Nie wprowadzono żadnych zmian w danych klubu. Anulowanie.", color=0xe74c3c))
            await asyncio.sleep(3); await _safe_delete_channel(kanal); return

        # 5. Powód
        powod = await _zadaj_pytanie(kanal, user, "Podaj powód wprowadzanych zmian:", client)

        embed = discord.Embed(title="⚙️ Wniosek o Aktualizację Klubu", color=0x9b59b6)
        embed.add_field(name="Klub", value=f"`{user_club}`" if nowy_tag == user_club else f"`{user_club}` ➔ `{nowy_tag}`", inline=True)
        embed.add_field(name="Nazwa", value=nowa_nazwa if nowa_nazwa == stara_nazwa else f"~~{stara_nazwa}~~ ➔ **{nowa_nazwa}**", inline=True)
        embed.add_field(name="Właściciel", value=nowy_wlasciciel if nowy_wlasciciel == stary_wlasciciel else f"{nowy_wlasciciel} *(Nowy)*", inline=False)
        embed.add_field(name="Zarząd", value=nowy_zarzad if nowy_zarzad == stary_zarzad else f"{nowy_zarzad} *(Nowy)*", inline=False)
        embed.add_field(name="Powód", value=powod, inline=False)
        embed.add_field(name="Status", value="⏳ Oczekuje na decyzję Zarządu Federacji", inline=False)
        embed.set_footer(text=f"{league_config.league_name()} • Biuro")

        v = WniosekConfirmView(user.id)
        await kanal.send(embed=embed, view=v)
        await v.wait()
        if not v.value:
            await kanal.send(embed=discord.Embed(description="❌ Wniosek anulowany.", color=0xe74c3c))
            await asyncio.sleep(2); await _safe_delete_channel(kanal); return

        app_id = database.create_application(
            app_type="ZARZADZANIE_KLUBU", applicant_id=user.id,
            club_name=nowa_nazwa, club_tag=nowy_tag, old_club_tag=user_club,
            founder_txt=stary_wlasciciel, board_txt=stary_zarzad,
            new_founder_txt=nowy_wlasciciel, new_board_txt=nowy_zarzad,
            reason=powod
        )
        tag_display = f"{user_club} ➔ {nowy_tag}" if nowy_tag != user_club else user_club
        await _send_forum_application(guild, kanal, embed,
                                       f"[ZARZĄDZANIE] {tag_display} – {nowa_nazwa}", app_id)

    except TimeoutError:
        pass
    except Exception as e:
        print(f"[proces_zarzadzania_klubem] Błąd: {e}\n{traceback.format_exc()}")
        try: await kanal.send(embed=discord.Embed(description=f"❌ Błąd: `{e}`", color=0xe74c3c)); await asyncio.sleep(5); await _safe_delete_channel(kanal)
        except Exception: pass


