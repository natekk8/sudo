from datetime import datetime
import discord
from discord.ext import tasks
import database
from config import CHANNEL_KOMUNIKATY_ID

def setup_expirations_task(bot: discord.Client):
    @tasks.loop(minutes=60)
    async def check_expirations():
        await bot.wait_until_ready()
        guild = bot.guilds[0] if bot.guilds else None
        if not guild:
            return

        kom_channel = guild.get_channel(CHANNEL_KOMUNIKATY_ID)
        now = datetime.now()
        players = database.get_all_players()

        for player in players:
            wazny_do_str = player.get("expires_at")
            if not wazny_do_str:
                continue

            try:
                wazny_do = datetime.strptime(wazny_do_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            if now >= wazny_do:
                gracz_nazwa = player.get("name")
                typ = player.get("contract_type")
                klub_obecny = player.get("club_tag")
                klub_macierzysty = player.get("parent_club_tag") or klub_obecny
                dc_id = player.get("discord_id")
                member = guild.get_member(dc_id) if dc_id else None

                c_obecny = database.get_club(klub_obecny)
                c_macierz = database.get_club(klub_macierzysty)

                # ==================== WYPOŻYCZENIE ====================
                if typ == "WYPOZYCZENIE":
                    if member:
                        if c_obecny:
                            r_temp = guild.get_role(c_obecny.get("role_player_id", 0))
                            if r_temp:
                                try: await member.remove_roles(r_temp)
                                except Exception as e: print(f"Błąd odebrania roli wypożyczenia: {e}")
                        if c_macierz:
                            r_mac = guild.get_role(c_macierz.get("role_player_id", 0))
                            if r_mac:
                                try: await member.add_roles(r_mac)
                                except Exception as e: print(f"Błąd nadania roli macierzystej: {e}")

                    database.add_or_update_player(
                        name=gracz_nazwa,
                        discord_id=dc_id,
                        club_tag=klub_macierzysty,
                        parent_club_tag=klub_macierzysty,
                        clause=player.get("clause", "Brak"),
                        contract_type="TRANSFER",
                        expires_at=None
                    )

                    if kom_channel:
                        nazwa_obecny = c_obecny.get("name", klub_obecny) if c_obecny else klub_obecny
                        nazwa_macierz = c_macierz.get("name", klub_macierzysty) if c_macierz else klub_macierzysty
                        await kom_channel.send(
                            f"⏱️ **KONIEC WYPOŻYCZENIA!**\n"
                            f"> Zawodnik **{gracz_nazwa}** zakończył okres wypożyczenia w **{nazwa_obecny}** "
                            f"i wraca do macierzystego klubu **{nazwa_macierz}** (`{klub_macierzysty}`)!"
                        )

                # ==================== KONTRAKT ZWYKŁY ====================
                else:
                    if member and c_obecny:
                        r_zaw = guild.get_role(c_obecny.get("role_player_id", 0))
                        if r_zaw:
                            try: await member.remove_roles(r_zaw)
                            except Exception as e: print(f"Błąd odebrania roli po wygaśnięciu kontraktu: {e}")

                    database.delete_player(gracz_nazwa)

                    if kom_channel:
                        nazwa_klub = c_obecny.get("name", klub_obecny) if c_obecny else klub_obecny
                        await kom_channel.send(
                            f"📢 **WYGAŚNIĘCIE KONTRAKTU!**\n"
                            f"> Kontrakt zawodnika **{gracz_nazwa}** z drużyną **{nazwa_klub}** (`{klub_obecny}`) dobiegł końca.\n"
                            f"> Zawodnik staje się graczem bez klubu!"
                        )

    return check_expirations
