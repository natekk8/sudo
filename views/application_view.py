import discord
from discord import ui
import database
from config import ROLE_FEDERACJA_ID, ROLA_WZORZEC_ID, CHANNEL_KOMUNIKATY_ID, MAX_PLAYERS_PER_CLUB
from utils.helpers import (
    is_federation, is_club_board_or_owner, extract_ids, clean_tag,
    send_dm, format_expiry_discord, get_or_fetch_member
)

_HISTORY_EMOJIS = {
    "TRANSFER": "🤝",
    "WYKUP": "🔥",
    "PODPISANIE": "📝",
    "BEZ_KLUBU": "📝",
    "WYPOZYCZENIE": "⏱️",
    "POWROT_Z_WYPOZYCZENIA": "↩️",
    "ANEKS": "📄",
    "ROZWIAZANIE_POLUBOWNE": "🤝",
    "ROZWIAZANIE_DYSCYPLINARNE": "⚖️",
    "WYGASNIECIE": "📄",
}


class ForumApplicationView(ui.View):
    def __init__(self, app_id: int):
        super().__init__(timeout=None)
        self.app_id = app_id
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        app = database.get_application(self.app_id)
        if not app or app.get("status") not in ("PENDING", "PROCESSING"):
            return

        app_type = app.get("type")
        is_transfer_type = app_type in ("TRANSFER", "WYPOZYCZENIE", "PODPISANIE", "ANEKS", "ROZWIAZANIE_POLUBOWNE")

        # ── Zgoda gracza ──
        if app.get("needs_player_agree") and is_transfer_type:
            if app.get("player_agreed"):
                btn = ui.Button(label="Zgoda gracza ✅", style=discord.ButtonStyle.green,
                                disabled=True, custom_id=f"app:{self.app_id}:p_agree")
            else:
                btn = ui.Button(label="✍️ Zgoda gracza", style=discord.ButtonStyle.primary,
                                custom_id=f"app:{self.app_id}:p_agree")
                btn.callback = self.cb_player_agree
            self.add_item(btn)

        # ── Zgoda kupującego / przyjmującego ──
        if app.get("needs_target_club_agree"):
            t_label = {
                "PODPISANIE": "Zgoda klubu",
                "TRANSFER": "Zgoda kupującego",
                "WYPOZYCZENIE": "Zgoda przyjmującego",
                "ANEKS": "Zgoda zarządu",
            }.get(app_type, "Zgoda klubu")
            if app.get("target_club_agreed"):
                btn = ui.Button(label=f"{t_label} ✅", style=discord.ButtonStyle.green,
                                disabled=True, custom_id=f"app:{self.app_id}:t_agree")
            else:
                btn = ui.Button(label=f"🤝 {t_label}", style=discord.ButtonStyle.secondary,
                                custom_id=f"app:{self.app_id}:t_agree")
                btn.callback = self.cb_target_agree
            self.add_item(btn)

        # ── Zgoda sprzedającego / oddającego ──
        if app.get("needs_source_club_agree"):
            s_label = "Zgoda sprzedającego" if app_type == "TRANSFER" else "Zgoda oddającego"
            if app.get("source_club_agreed"):
                btn = ui.Button(label=f"{s_label} ✅", style=discord.ButtonStyle.green,
                                disabled=True, custom_id=f"app:{self.app_id}:s_agree")
            else:
                btn = ui.Button(label=f"🤝 {s_label}", style=discord.ButtonStyle.secondary,
                                custom_id=f"app:{self.app_id}:s_agree")
                btn.callback = self.cb_source_agree
            self.add_item(btn)

        # ── Odrzuć ofertę (tylko dla typów niebędących rebrandingiem/rejestracji) ──
        if app_type not in ("REJESTRACJA_KLUBU", "REBRAND_KLUBU", "ROZWIAZANIE_DYSCYPLINARNE"):
            btn_rp = ui.Button(label="❌ Odrzuć ofertę", style=discord.ButtonStyle.danger,
                               custom_id=f"app:{self.app_id}:party_reject")
            btn_rp.callback = self.cb_party_reject
            self.add_item(btn_rp)

        # ── Historia transferów (tylko dla wniosków dot. gracza) ──
        if app.get("player_name") and app_type not in ("REJESTRACJA_KLUBU", "REBRAND_KLUBU"):
            btn_h = ui.Button(label="📜 Poprzednie kluby", style=discord.ButtonStyle.secondary,
                              custom_id=f"app:{self.app_id}:history")
            btn_h.callback = self.cb_history
            self.add_item(btn_h)

        # ── Federacja: Akceptuj i Odrzuć (zawsze aktywne) ──
        btn_acc = ui.Button(label="✅ Akceptuj", style=discord.ButtonStyle.green,
                            custom_id=f"app:{self.app_id}:fed_accept")
        btn_acc.callback = self.cb_fed_accept
        self.add_item(btn_acc)

        btn_rej = ui.Button(label="❌ Odrzuć", style=discord.ButtonStyle.red,
                            custom_id=f"app:{self.app_id}:fed_reject")
        btn_rej.callback = self.cb_fed_reject
        self.add_item(btn_rej)

    # ─────────────────────────────── ZGODY STRON ──────────────────────────────

    async def cb_player_agree(self, interaction: discord.Interaction):
        app = database.get_application(self.app_id)
        if not app or app.get("status") not in ("PENDING", "PROCESSING"):
            return await interaction.response.send_message("❌ Ten wniosek jest już zamknięty.", ephemeral=True)
        if interaction.user.id != app.get("player_discord_id"):
            return await interaction.response.send_message(
                "❌ Tylko wskazany zawodnik może kliknąć ten przycisk!", ephemeral=True)
        database.set_application_agreement(self.app_id, "player", True)
        self._build_buttons()
        embed = self._update_status_field(interaction.message.embeds[0], database.get_application(self.app_id))
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send("✅ Złożono podpis zawodnika.", ephemeral=True)

    async def cb_target_agree(self, interaction: discord.Interaction):
        app = database.get_application(self.app_id)
        if not app or app.get("status") not in ("PENDING", "PROCESSING"):
            return await interaction.response.send_message("❌ Ten wniosek jest już zamknięty.", ephemeral=True)
        target = app.get("target_club")
        if not is_club_board_or_owner(interaction.user, target):
            return await interaction.response.send_message(
                f"❌ Tylko Zarząd/Właściciel klubu `{target}` może wyrazić zgodę!", ephemeral=True)
        database.set_application_agreement(self.app_id, "target_club", True)
        self._build_buttons()
        embed = self._update_status_field(interaction.message.embeds[0], database.get_application(self.app_id))
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send("✅ Udzielono zgody klubu.", ephemeral=True)

    async def cb_source_agree(self, interaction: discord.Interaction):
        app = database.get_application(self.app_id)
        if not app or app.get("status") not in ("PENDING", "PROCESSING"):
            return await interaction.response.send_message("❌ Ten wniosek jest już zamknięty.", ephemeral=True)
        source = app.get("source_club")
        if not is_club_board_or_owner(interaction.user, source):
            return await interaction.response.send_message(
                f"❌ Tylko Zarząd/Właściciel klubu `{source}` może wyrazić zgodę!", ephemeral=True)
        database.set_application_agreement(self.app_id, "source_club", True)
        self._build_buttons()
        embed = self._update_status_field(interaction.message.embeds[0], database.get_application(self.app_id))
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send("✅ Udzielono zgody klubu oddającego/sprzedającego.", ephemeral=True)

    async def cb_party_reject(self, interaction: discord.Interaction):
        app = database.get_application(self.app_id)
        if not app or app.get("status") not in ("PENDING", "PROCESSING"):
            return await interaction.response.send_message("❌ Ten wniosek jest już zamknięty.", ephemeral=True)

        user = interaction.user
        app_type = app.get("type")
        rejected_by = None

        if app.get("player_discord_id") and user.id == app.get("player_discord_id"):
            rejected_by = f"Zawodnik: <@{user.id}>"
        elif is_club_board_or_owner(user, app.get("target_club")):
            rejected_by = f"Zarząd kupującego/przyjmującego (`{app.get('target_club', '')}`): <@{user.id}>"
        elif app.get("source_club") and is_club_board_or_owner(user, app.get("source_club")):
            # Blokada odrzucania wykupu klauzulowego przez sprzedającego
            if app.get("is_buyout") or (app_type == "TRANSFER" and not app.get("needs_source_club_agree")):
                return await interaction.response.send_message(
                    "❌ **To jest wykup klauzulowy** – klub sprzedający nie może zablokować tego transferu!\n"
                    "Kwota wykupu spełnia warunki klauzuli odstępnego.", ephemeral=True)
            rejected_by = f"Zarząd sprzedającego/oddającego (`{app.get('source_club', '')}`): <@{user.id}>"
        else:
            return await interaction.response.send_message(
                "❌ Nie jesteś stroną tego wniosku.", ephemeral=True)

        database.set_application_status(self.app_id, "REJECTED_BY_PARTY", rejected_by=rejected_by)
        embed = interaction.message.embeds[0]
        embed.color = 0xe74c3c
        embed.title = f"❌ {embed.title or 'Wniosek'}"
        embed.add_field(name="Odrzucono przez", value=rejected_by, inline=False)
        await interaction.response.edit_message(embed=embed, view=None)
        await self._archive_thread(interaction.channel)
        await interaction.followup.send(f"Wniosek odrzucony przez: {rejected_by}.", ephemeral=True)

    async def cb_history(self, interaction: discord.Interaction):
        app = database.get_application(self.app_id)
        if not app:
            return await interaction.response.send_message("❌ Nie znaleziono wniosku.", ephemeral=True)
        player_name = app.get("player_name", "")
        player_dc_id = app.get("player_discord_id")
        history = database.get_player_transfer_history(player_name, player_dc_id)
        if not history:
            return await interaction.response.send_message(
                f"📜 Zawodnik **{player_name}** nie posiada historii transferów.", ephemeral=True)

        lines = []
        for h in history:
            from_c = h.get("from_club") or "Wolny Agent"
            to_c = h.get("to_club") or "Wolny Agent"
            typ = h.get("transfer_type", "")
            amount = h.get("amount")
            date_str = h.get("date", "")[:10]
            emoji = _HISTORY_EMOJIS.get(typ, "📋")
            amount_str = f" · `{amount}`" if amount and amount.lower() not in ("brak", "bez zmian") else ""
            # Czytelny opis wygaśnięcia
            if typ == "WYGASNIECIE":
                line = f"{emoji} `{date_str}` **{from_c}** ➔ Wolny Agent *(Koniec umowy)*{amount_str}"
            else:
                line = f"{emoji} `{date_str}` **{from_c}** ➔ **{to_c}**{amount_str}"
            lines.append(line)

        embed = discord.Embed(
            title=f"📜 Historia transferów: {player_name}",
            description="\n".join(lines),
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ───────────────────────────── FEDERACJA ──────────────────────────────────

    async def cb_fed_accept(self, interaction: discord.Interaction):
        if not is_federation(interaction.user):
            return await interaction.response.send_message(
                "❌ Tylko Zarząd Federacji może zatwierdzić wniosek.", ephemeral=True)

        await interaction.response.defer()

        # ── Atomowy CAS: PENDING → PROCESSING (ochrona przed race conditions) ──
        app = database.try_claim_application_for_approval(self.app_id)
        if not app:
            return await interaction.followup.send(
                "❌ Ten wniosek jest już przetwarzany lub został wcześniej zamknięty.", ephemeral=True)

        app_type = app.get("type")
        guild = interaction.guild
        kom_channel = guild.get_channel(CHANNEL_KOMUNIKATY_ID)

        try:
            await self._execute_accept(interaction, app, app_type, guild, kom_channel)
        except Exception as e:
            # Rollback statusu PROCESSING → PENDING przy błędzie krytycznym
            database.revert_application_status(self.app_id)
            print(f"[ForumView] BŁĄD w cb_fed_accept (app #{self.app_id}): {e}")
            await interaction.followup.send(
                f"❌ Wystąpił błąd podczas przetwarzania wniosku. Status cofnięty do PENDING.\n`{e}`",
                ephemeral=True
            )
            raise

    async def _execute_accept(self, interaction, app, app_type, guild, kom_channel):
        # ─── REJESTRACJA KLUBU ───
        if app_type == "REJESTRACJA_KLUBU":
            from config import ROLA_WZORZEC_ID
            from utils.helpers import extract_ids
            skrot = clean_tag(app.get("club_tag"))
            nazwa = app.get("club_name")
            base_role = guild.get_role(ROLA_WZORZEC_ID)
            board_perms = base_role.permissions if base_role else discord.Permissions.none()

            r_zarzad = await guild.create_role(
                name=f"⚽・{skrot} - Zarząd", permissions=board_perms, hoist=bool(base_role and base_role.hoist))
            r_zawod = await guild.create_role(name=f"⚽・{skrot} - Zawodnik")

            founder_ids = extract_ids(app.get("founder_txt", ""))
            board_ids = extract_ids(app.get("board_txt", ""))
            osoby = set(founder_ids + board_ids)
            if app.get("applicant_id"): osoby.add(app["applicant_id"])

            for uid in osoby:
                m = await get_or_fetch_member(guild, uid)
                if m:
                    try: await m.add_roles(r_zarzad)
                    except Exception as e: print(f"[Fed] Błąd nadania roli {uid}: {e}")

            database.add_club(
                tag=skrot, name=nazwa,
                role_board_id=r_zarzad.id, role_player_id=r_zawod.id,
                reprezentant_dc=app.get("applicant_id"),
                founder_txt=app.get("founder_txt", ""),
                board_txt=app.get("board_txt", ""),
                board_ids=list(osoby)
            )
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ Zaakceptowano: {nazwa}"
            embed.add_field(name="Decyzja Federacji",
                            value=f"Zatwierdzono przez {interaction.user.mention}.", inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                await kom_channel.send(
                    f"📢 **NOWY KLUB!** Zespół **{nazwa}** (`{skrot}`) został zarejestrowany w lidze!",
                    allowed_mentions=discord.AllowedMentions.none()
                )

        # ─── PODPISANIE ───
        elif app_type == "PODPISANIE":
            target_club = clean_tag(app.get("target_club"))
            if database.get_club_player_count(target_club) >= MAX_PLAYERS_PER_CLUB:
                database.revert_application_status(self.app_id)
                return await interaction.followup.send(
                    f"❌ Klub `{target_club}` osiągnął limit {MAX_PLAYERS_PER_CLUB}/{MAX_PLAYERS_PER_CLUB} graczy!", ephemeral=True)

            gracz = app.get("player_name")
            dc_id = app.get("player_discord_id")
            c_target = database.get_club(target_club)

            if dc_id:
                m = await get_or_fetch_member(guild, dc_id)
                if m and c_target:
                    r = guild.get_role(c_target.get("role_player_id", 0))
                    if r:
                        try: await m.add_roles(r)
                        except Exception as e: print(f"[Fed] Błąd roli: {e}")
                database.remove_free_agent(dc_id)

            database.add_or_update_player(
                name=gracz, discord_id=dc_id, club_tag=target_club, parent_club_tag=target_club,
                clause=app.get("clause", "Brak"), contract_type="BEZ_KLUBU",
                expires_at=app.get("expires_at")
            )
            database.add_transfer_history(gracz, dc_id, None, target_club, "PODPISANIE", None)
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ PODPISANIE: {gracz}"
            for i, f in enumerate(embed.fields):
                if f.name == "Status":
                    embed.set_field_at(i, name="Status",
                                       value=f"✅ Zatwierdzone przez Federację ({interaction.user.mention})", inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                c_nazwa = c_target.get("name", target_club) if c_target else target_club
                await kom_channel.send(
                    f"📢 **OFICJALNIE:** Zawodnik **{gracz}** dołącza do **{c_nazwa}** (`{target_club}`)!\n"
                    f"> Ważność: `{app.get('expires_at')}` | Klauzula: `{app.get('clause')}`",
                    allowed_mentions=discord.AllowedMentions.none()
                )
            if dc_id:
                await send_dm(interaction.client, dc_id,
                              f"📄 Twój kontrakt z `{target_club}` został zatwierdzony!\n"
                              f"> Ważność: `{app.get('expires_at')}` | Klauzula: `{app.get('clause')}`")

        # ─── TRANSFER ───
        elif app_type == "TRANSFER":
            target_club = clean_tag(app.get("target_club"))
            source_club = clean_tag(app.get("source_club"))
            if database.get_club_player_count(target_club) >= MAX_PLAYERS_PER_CLUB:
                database.revert_application_status(self.app_id)
                return await interaction.followup.send(
                    f"❌ Klub `{target_club}` jest już pełny ({MAX_PLAYERS_PER_CLUB}/{MAX_PLAYERS_PER_CLUB})!", ephemeral=True)

            gracz = app.get("player_name")
            dc_id = app.get("player_discord_id")
            c_target = database.get_club(target_club)
            c_source = database.get_club(source_club)

            if dc_id:
                m = await get_or_fetch_member(guild, dc_id)
                if m:
                    if c_source:
                        r_old = guild.get_role(c_source.get("role_player_id", 0))
                        if r_old:
                            try: await m.remove_roles(r_old)
                            except Exception: pass
                    if c_target:
                        r_new = guild.get_role(c_target.get("role_player_id", 0))
                        if r_new:
                            try: await m.add_roles(r_new)
                            except Exception: pass
                database.remove_free_agent(dc_id)

            database.add_or_update_player(
                name=gracz, discord_id=dc_id, club_tag=target_club, parent_club_tag=target_club,
                clause=app.get("clause", "Brak"), contract_type="TRANSFER",
                expires_at=app.get("expires_at")
            )
            transfer_type = "WYKUP" if app.get("is_buyout") else "TRANSFER"
            database.add_transfer_history(gracz, dc_id, source_club, target_club, transfer_type, app.get("amount"))
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ TRANSFER: {gracz}"
            for i, f in enumerate(embed.fields):
                if f.name == "Status":
                    embed.set_field_at(i, name="Status",
                                       value=f"✅ Zatwierdzono ({interaction.user.mention})", inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                t_nazwa = c_target.get("name", target_club) if c_target else target_club
                hype = "🔥🚨 **BOMBA TRANSFEROWA!**" if app.get("is_buyout") else "📢 **OFICJALNIE:**"
                await kom_channel.send(
                    f"{hype} Zawodnik **{gracz}** przechodzi do **{t_nazwa}** (`{target_club}`)!\n"
                    f"> Kwota: `{app.get('amount')}` | Nowa klauzula: `{app.get('clause')}` | Umowa do: `{app.get('expires_at')}`",
                    allowed_mentions=discord.AllowedMentions.none()
                )
            if dc_id:
                await send_dm(interaction.client, dc_id,
                              f"📄 Transfer do `{target_club}` zatwierdzony!\n"
                              f"> Umowa do `{app.get('expires_at')}` | Klauzula `{app.get('clause')}`")

        # ─── WYPOŻYCZENIE ───
        elif app_type == "WYPOZYCZENIE":
            target_club = clean_tag(app.get("target_club"))
            source_club = clean_tag(app.get("source_club"))
            if database.get_club_player_count(target_club) >= MAX_PLAYERS_PER_CLUB:
                database.revert_application_status(self.app_id)
                return await interaction.followup.send(
                    f"❌ Klub `{target_club}` jest już pełny ({MAX_PLAYERS_PER_CLUB}/{MAX_PLAYERS_PER_CLUB})!", ephemeral=True)

            gracz = app.get("player_name")
            dc_id = app.get("player_discord_id")
            c_target = database.get_club(target_club)
            c_source = database.get_club(source_club)

            existing = database.get_player(gracz)
            if not existing and dc_id:
                existing = database.get_player_by_discord_id(dc_id)
            parent_expires = existing.get("expires_at") if existing else None
            parent_clause_val = existing.get("clause", "Brak") if existing else "Brak"

            if dc_id:
                m = await get_or_fetch_member(guild, dc_id)
                if m:
                    if c_source:
                        r_old = guild.get_role(c_source.get("role_player_id", 0))
                        if r_old:
                            try: await m.remove_roles(r_old)
                            except Exception: pass
                    if c_target:
                        r_new = guild.get_role(c_target.get("role_player_id", 0))
                        if r_new:
                            try: await m.add_roles(r_new)
                            except Exception: pass
                database.remove_free_agent(dc_id)

            database.add_or_update_player(
                name=gracz, discord_id=dc_id, club_tag=target_club, parent_club_tag=source_club,
                clause=parent_clause_val, contract_type="WYPOZYCZENIE",
                expires_at=app.get("expires_at"),
                parent_contract_expires_at=parent_expires,
                parent_clause=parent_clause_val  # Ochrona klauzuli macierzystej
            )
            database.add_transfer_history(gracz, dc_id, source_club, target_club, "WYPOZYCZENIE", app.get("amount"))
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ WYPOŻYCZENIE: {gracz}"
            for i, f in enumerate(embed.fields):
                if f.name == "Status":
                    embed.set_field_at(i, name="Status",
                                       value=f"✅ Zatwierdzono ({interaction.user.mention})", inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                t_nazwa = c_target.get("name", target_club) if c_target else target_club
                await kom_channel.send(
                    f"📢 **OFICJALNIE:** Zawodnik **{gracz}** wypożyczony do **{t_nazwa}** (`{target_club}`)!\n"
                    f"> Koniec wypożyczenia: `{app.get('expires_at')}` | Opłata: `{app.get('amount')}`",
                    allowed_mentions=discord.AllowedMentions.none()
                )
            if dc_id:
                await send_dm(interaction.client, dc_id,
                              f"📄 Wypożyczenie do `{target_club}` zatwierdzone!\n> Powrót: `{app.get('expires_at')}`")

        # ─── ANEKS DO KONTRAKTU ───
        elif app_type == "ANEKS":
            gracz = app.get("player_name")
            dc_id = app.get("player_discord_id")
            target_club = clean_tag(app.get("target_club"))
            new_expires = app.get("expires_at")
            new_clause = app.get("clause", "Brak")

            database.extend_player_contract(gracz, new_expires, new_clause)
            database.add_transfer_history(gracz, dc_id, target_club, target_club, "ANEKS", None)
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ ANEKS: {gracz}"
            embed.add_field(name="Decyzja Federacji",
                            value=f"Zatwierdzono przez {interaction.user.mention}.", inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                c_info = database.get_club(target_club)
                c_nazwa = c_info.get("name", target_club) if c_info else target_club
                await kom_channel.send(
                    f"📄 **PRZEDŁUŻENIE KONTRAKTU:** Zawodnik **{gracz}** przedłużył umowę z **{c_nazwa}** (`{target_club}`)!\n"
                    f"> Nowy termin: `{new_expires}` | Klauzula: `{new_clause}`",
                    allowed_mentions=discord.AllowedMentions.none()
                )
            if dc_id:
                await send_dm(interaction.client, dc_id,
                              f"📄 Twój aneks do kontraktu w `{target_club}` został zatwierdzony!\n"
                              f"> Nowy termin: `{new_expires}` | Klauzula: `{new_clause}`")

        # ─── ROZWIĄZANIE KONTRAKTU ───
        elif app_type in ("ROZWIAZANIE_POLUBOWNE", "ROZWIAZANIE_DYSCYPLINARNE"):
            gracz = app.get("player_name")
            dc_id = app.get("player_discord_id")
            source_club = clean_tag(app.get("source_club"))
            c_source = database.get_club(source_club)

            if dc_id:
                m = await get_or_fetch_member(guild, dc_id)
                if m and c_source:
                    r = guild.get_role(c_source.get("role_player_id", 0))
                    if r:
                        try: await m.remove_roles(r)
                        except Exception as e: print(f"[Fed] Błąd usunięcia roli: {e}")

            database.terminate_player_contract(gracz)
            trans_typ = "ROZWIAZANIE_DYSCYPLINARNE" if app_type == "ROZWIAZANIE_DYSCYPLINARNE" else "ROZWIAZANIE_POLUBOWNE"
            database.add_transfer_history(gracz, dc_id, source_club, None, trans_typ, None)
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0xe67e22
            tryb = "dyscyplinarnie" if app_type == "ROZWIAZANIE_DYSCYPLINARNE" else "za porozumieniem stron"
            embed.title = f"✅ ROZWIĄZANIE UMOWY ({tryb.upper()}): {gracz}"
            embed.add_field(name="Decyzja Federacji",
                            value=f"Zatwierdzone przez {interaction.user.mention}.", inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                c_nazwa = c_source.get("name", source_club) if c_source else source_club
                await kom_channel.send(
                    f"📢 Kontrakt zawodnika **{gracz}** z **{c_nazwa}** (`{source_club}`) został rozwiązany ({tryb}).",
                    allowed_mentions=discord.AllowedMentions.none()
                )
            if dc_id:
                await send_dm(interaction.client, dc_id,
                              f"📢 Twój kontrakt z `{source_club}` został rozwiązany ({tryb}).\n"
                              "Jeśli szukasz nowego klubu, zarejestruj się na Giełdzie Wolnych Agentów!")

        # ─── REBRANDING KLUBU ───
        elif app_type == "REBRAND_KLUBU":
            old_tag = clean_tag(app.get("old_club_tag"))
            new_tag = clean_tag(app.get("club_tag"))
            new_name = app.get("club_name")
            c_old = database.get_club(old_tag)

            database.rebrand_club(old_tag, new_tag, new_name)

            # Zmień nazwy ról na Discordzie
            if c_old:
                r_board = guild.get_role(c_old.get("role_board_id", 0))
                r_player = guild.get_role(c_old.get("role_player_id", 0))
                if r_board:
                    try: await r_board.edit(name=f"⚽・{new_tag} - Zarząd")
                    except Exception as e: print(f"[Fed] Błąd rebrand roli zarządu: {e}")
                if r_player:
                    try: await r_player.edit(name=f"⚽・{new_tag} - Zawodnik")
                    except Exception as e: print(f"[Fed] Błąd rebrand roli zawodnika: {e}")

            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x9b59b6
            embed.title = f"✅ REBRANDING: `{old_tag}` ➔ `{new_tag}`"
            embed.add_field(name="Decyzja Federacji",
                            value=f"Zatwierdzone przez {interaction.user.mention}.", inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                await kom_channel.send(
                    f"🔄 **REBRANDING!** Klub `{old_tag}` zmienił nazwę na **{new_name}** (`{new_tag}`)!",
                    allowed_mentions=discord.AllowedMentions.none()
                )

        # ─── Archiwizacja wątku ───
        await self._archive_thread(interaction.channel)

    async def cb_fed_reject(self, interaction: discord.Interaction):
        if not is_federation(interaction.user):
            return await interaction.response.send_message(
                "❌ Tylko Zarząd Federacji może odrzucić wniosek.", ephemeral=True)

        await interaction.response.defer()

        app = database.try_claim_application_for_approval(self.app_id)
        if not app:
            return await interaction.followup.send("❌ Ten wniosek jest już zamknięty lub przetwarzany.", ephemeral=True)

        database.set_application_status(self.app_id, "REJECTED",
                                         rejected_by=f"Federacja ({interaction.user.mention})")
        embed = interaction.message.embeds[0]
        embed.color = 0xe74c3c
        embed.title = f"❌ ODRZUCONO: {embed.title or 'Wniosek'}"
        embed.add_field(name="Decyzja Federacji",
                        value=f"Wniosek odrzucony przez {interaction.user.mention}.", inline=False)
        await interaction.message.edit(embed=embed, view=None)
        await self._archive_thread(interaction.channel)

    # ─────────────────────────── POMOCNICZE ───────────────────────────────────

    def _update_status_field(self, embed: discord.Embed, app: dict) -> discord.Embed:
        if not app: return embed
        lines = []
        if app.get("needs_player_agree"):
            lines.append(f"• Zawodnik: {'✅ Udzielono' if app.get('player_agreed') else '⏳ Oczekuje'}")
        else:
            lines.append("• Zawodnik: ℹ️ Brak konta Discord")
        target = app.get("target_club", "")
        if app.get("needs_target_club_agree"):
            lines.append(f"• Klub `{target}`: {'✅ Zgoda' if app.get('target_club_agreed') else '⏳ Oczekuje'}")
        elif target:
            lines.append(f"• Klub `{target}`: ℹ️ Brak kont DC zarządu")
        source = app.get("source_club", "")
        if source and app.get("needs_source_club_agree"):
            lines.append(f"• Klub `{source}`: {'✅ Zgoda' if app.get('source_club_agreed') else '⏳ Oczekuje'}")
        elif source and app.get("is_buyout"):
            lines.append(f"• Klub `{source}`: ⚡ Wykup klauzulowy (zgoda zbędna)")
        lines.append("• Zarząd Federacji: ⏳ Oczekuje")
        new_val = "\n".join(lines)
        for i, f in enumerate(embed.fields):
            if f.name == "Status":
                embed.set_field_at(i, name="Status", value=new_val, inline=False)
                return embed
        embed.add_field(name="Status", value=new_val, inline=False)
        return embed

    async def _archive_thread(self, channel):
        if isinstance(channel, discord.Thread):
            try:
                await channel.edit(locked=True, archived=True)
            except Exception as e:
                print(f"[ForumView] Błąd archiwizacji wątku: {e}")

def clean_tag(tag: str) -> str:
    if not tag: return ""
    return tag.strip().upper()
