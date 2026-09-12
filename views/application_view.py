import discord
from discord import ui
import database
from config import ROLE_FEDERACJA_ID, ROLA_WZORZEC_ID, CHANNEL_KOMUNIKATY_ID, MAX_PLAYERS_PER_CLUB
from utils.helpers import (
    is_federation, is_club_board_or_owner, extract_ids, clean_tag,
    send_dm, format_expiry_discord
)

class ForumApplicationView(ui.View):
    def __init__(self, app_id: int):
        super().__init__(timeout=None)
        self.app_id = app_id
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        app = database.get_application(self.app_id)
        if not app or app.get("status") != "PENDING":
            return

        app_type = app.get("type")

        # ── Zgoda gracza (tylko gdy gracz ma konto Discord i nie wyraził jeszcze zgody) ──
        if app.get("needs_player_agree"):
            if app.get("player_agreed"):
                btn = ui.Button(label="Zgoda gracza", style=discord.ButtonStyle.green,
                                emoji="✅", disabled=True,
                                custom_id=f"app:{self.app_id}:p_agree")
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
                "WYPOZYCZENIE": "Zgoda przyjmującego"
            }.get(app_type, "Zgoda klubu")

            if app.get("target_club_agreed"):
                btn = ui.Button(label=t_label, style=discord.ButtonStyle.green,
                                emoji="✅", disabled=True,
                                custom_id=f"app:{self.app_id}:t_agree")
            else:
                btn = ui.Button(label=f"🤝 {t_label}", style=discord.ButtonStyle.secondary,
                                custom_id=f"app:{self.app_id}:t_agree")
                btn.callback = self.cb_target_agree
            self.add_item(btn)

        # ── Zgoda sprzedającego / oddającego (transfer/wypożyczenie, jeśli wymagana) ──
        if app.get("needs_source_club_agree"):
            s_label = "Zgoda sprzedającego" if app_type == "TRANSFER" else "Zgoda oddającego"

            if app.get("source_club_agreed"):
                btn = ui.Button(label=s_label, style=discord.ButtonStyle.green,
                                emoji="✅", disabled=True,
                                custom_id=f"app:{self.app_id}:s_agree")
            else:
                btn = ui.Button(label=f"🤝 {s_label}", style=discord.ButtonStyle.secondary,
                                custom_id=f"app:{self.app_id}:s_agree")
                btn.callback = self.cb_source_agree
            self.add_item(btn)

        # ── Jeden przycisk Odrzuć ofertę dla stron (gracz, zarządy) ──
        if app_type != "REJESTRACJA_KLUBU":
            btn_reject_party = ui.Button(
                label="❌ Odrzuć ofertę",
                style=discord.ButtonStyle.danger,
                custom_id=f"app:{self.app_id}:party_reject"
            )
            btn_reject_party.callback = self.cb_party_reject
            self.add_item(btn_reject_party)

        # ── Historia transferów gracza (przycisk podglądu) ──
        if app_type != "REJESTRACJA_KLUBU":
            btn_hist = ui.Button(
                label="📜 Poprzednie kluby",
                style=discord.ButtonStyle.secondary,
                custom_id=f"app:{self.app_id}:history"
            )
            btn_hist.callback = self.cb_history
            self.add_item(btn_hist)

        # ── Federacja: Akceptuj i Odrzuć (zawsze aktywne, bez blokad) ──
        btn_accept = ui.Button(label="✅ Akceptuj", style=discord.ButtonStyle.green,
                               custom_id=f"app:{self.app_id}:fed_accept")
        btn_accept.callback = self.cb_fed_accept
        self.add_item(btn_accept)

        btn_reject = ui.Button(label="❌ Odrzuć", style=discord.ButtonStyle.red,
                               custom_id=f"app:{self.app_id}:fed_reject")
        btn_reject.callback = self.cb_fed_reject
        self.add_item(btn_reject)

    def _update_embed_status(self, embed: discord.Embed, app: dict) -> discord.Embed:
        app_type = app.get("type")
        if app_type == "REJESTRACJA_KLUBU":
            return embed

        lines = []

        if app.get("needs_player_agree"):
            p_st = "✅ Udzielono" if app.get("player_agreed") else "⏳ Oczekuje"
            lines.append(f"• Zawodnik: {p_st}")
        else:
            lines.append("• Zawodnik: ℹ️ Brak konta Discord")

        target = app.get("target_club", "")
        if app.get("needs_target_club_agree"):
            t_st = "✅ Zgoda" if app.get("target_club_agreed") else "⏳ Oczekuje"
            lines.append(f"• Klub `{target}`: {t_st}")
        elif target:
            lines.append(f"• Klub `{target}`: ℹ️ Brak oznaczonych kont DC zarządu")

        if app_type in ("TRANSFER", "WYPOZYCZENIE"):
            source = app.get("source_club", "")
            if app.get("needs_source_club_agree"):
                s_st = "✅ Zgoda" if app.get("source_club_agreed") else "⏳ Oczekuje"
                lines.append(f"• Klub `{source}`: {s_st}")
            elif app_type == "TRANSFER" and not app.get("needs_source_club_agree"):
                lines.append(f"• Klub `{source}`: ⚡ Wykup klauzulowy")
            elif source:
                lines.append(f"• Klub `{source}`: ℹ️ Brak oznaczonych kont DC zarządu")

        lines.append("• Zarząd Federacji: ⏳ Oczekuje na decyzję")

        new_value = "\n".join(lines)
        for i, field in enumerate(embed.fields):
            if field.name == "Status":
                embed.set_field_at(i, name="Status", value=new_value, inline=False)
                return embed
        embed.add_field(name="Status", value=new_value, inline=False)
        return embed

    # ──────────────────────────────────────────
    # CALLBACKS ZGÓD
    # ──────────────────────────────────────────
    async def cb_player_agree(self, interaction: discord.Interaction):
        app = database.get_application(self.app_id)
        if not app or app.get("status") != "PENDING":
            return await interaction.response.send_message("❌ Ten wniosek jest już zamknięty.", ephemeral=True)
        if interaction.user.id != app.get("player_discord_id"):
            return await interaction.response.send_message(
                "❌ Tylko wskazany zawodnik może kliknąć ten przycisk!", ephemeral=True)

        database.set_application_agreement(self.app_id, "player", True)
        self._build_buttons()
        embed = self._update_embed_status(interaction.message.embeds[0], database.get_application(self.app_id))
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send("✅ Złożono podpis zawodnika.", ephemeral=True)

    async def cb_target_agree(self, interaction: discord.Interaction):
        app = database.get_application(self.app_id)
        if not app or app.get("status") != "PENDING":
            return await interaction.response.send_message("❌ Ten wniosek jest już zamknięty.", ephemeral=True)
        target_club = app.get("target_club")
        if not is_club_board_or_owner(interaction.user, target_club):
            return await interaction.response.send_message(
                f"❌ Tylko Zarząd/Właściciel klubu `{target_club}` może wyrazić zgodę!", ephemeral=True)

        database.set_application_agreement(self.app_id, "target_club", True)
        self._build_buttons()
        embed = self._update_embed_status(interaction.message.embeds[0], database.get_application(self.app_id))
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send("✅ Udzielono zgody klubu.", ephemeral=True)

    async def cb_source_agree(self, interaction: discord.Interaction):
        app = database.get_application(self.app_id)
        if not app or app.get("status") != "PENDING":
            return await interaction.response.send_message("❌ Ten wniosek jest już zamknięty.", ephemeral=True)
        source_club = app.get("source_club")
        if not is_club_board_or_owner(interaction.user, source_club):
            return await interaction.response.send_message(
                f"❌ Tylko Zarząd/Właściciel klubu `{source_club}` może wyrazić zgodę!", ephemeral=True)

        database.set_application_agreement(self.app_id, "source_club", True)
        self._build_buttons()
        embed = self._update_embed_status(interaction.message.embeds[0], database.get_application(self.app_id))
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send("✅ Udzielono zgody klubu oddającego/sprzedającego.", ephemeral=True)

    async def cb_party_reject(self, interaction: discord.Interaction):
        """Jeden przycisk odrzucenia dla stron – gracz, zarząd kupujący, zarząd sprzedający."""
        app = database.get_application(self.app_id)
        if not app or app.get("status") != "PENDING":
            return await interaction.response.send_message("❌ Ten wniosek jest już zamknięty.", ephemeral=True)

        user = interaction.user
        app_type = app.get("type")
        rejected_by = None

        # Rozpoznanie strony odrzucającej
        if app.get("player_discord_id") and user.id == app.get("player_discord_id"):
            rejected_by = f"Zawodnik: <@{user.id}>"
        elif is_club_board_or_owner(user, app.get("target_club")):
            target = app.get("target_club", "")
            rejected_by = f"Zarząd kupującego/przyjmującego (`{target}`): <@{user.id}>"
        elif app.get("source_club") and is_club_board_or_owner(user, app.get("source_club")):
            source = app.get("source_club", "")
            rejected_by = f"Zarząd sprzedającego/oddającego (`{source}`): <@{user.id}>"
        else:
            return await interaction.response.send_message(
                "❌ Nie jesteś stroną tego wniosku. Skontaktuj się z Federacją, jeśli masz zastrzeżenia.",
                ephemeral=True
            )

        database.set_application_status(self.app_id, "REJECTED_BY_PARTY", rejected_by=rejected_by)

        embed = interaction.message.embeds[0]
        embed.color = 0xe74c3c
        old_title = embed.title or "Wniosek"
        embed.title = f"❌ {old_title}"
        embed.add_field(name="Odrzucono przez", value=rejected_by, inline=False)

        await interaction.response.edit_message(embed=embed, view=None)

        # Archiwizacja wątku
        thread = interaction.channel
        if isinstance(thread, discord.Thread):
            try:
                await thread.edit(locked=True, archived=True)
            except Exception as e:
                print(f"[ForumView] Błąd archiwizacji wątku: {e}")

        await interaction.followup.send(
            f"Wniosek został odrzucony przez: {rejected_by}.", ephemeral=True
        )

    async def cb_history(self, interaction: discord.Interaction):
        """Podgląd historii transferów gracza (ephemeral)."""
        app = database.get_application(self.app_id)
        if not app:
            return await interaction.response.send_message("❌ Nie znaleziono wniosku.", ephemeral=True)

        player_name = app.get("player_name", "")
        player_dc_id = app.get("player_discord_id")

        history = database.get_player_transfer_history(player_name, player_dc_id)

        if not history:
            return await interaction.response.send_message(
                f"📜 Zawodnik **{player_name}** nie posiada historii transferów w lidze.",
                ephemeral=True
            )

        lines = []
        for h in history:
            from_c = h.get("from_club") or "Wolny Agent"
            to_c = h.get("to_club") or "?"
            typ = h.get("transfer_type", "")
            amount = h.get("amount")
            date_str = h.get("date", "")[:10]
            emoji = "⏱️" if typ == "WYPOZYCZENIE" else ("🔥" if typ == "WYKUP" else "🤝")
            amount_str = f" · `{amount}`" if amount and amount.lower() != "brak" else ""
            lines.append(f"{emoji} `{date_str}` {from_c} ➔ **{to_c}**{amount_str}")

        embed = discord.Embed(
            title=f"📜 Historia transferów: {player_name}",
            description="\n".join(lines),
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ──────────────────────────────────────────
    # CALLBACKS FEDERACJI
    # ──────────────────────────────────────────
    async def cb_fed_accept(self, interaction: discord.Interaction):
        if not is_federation(interaction.user):
            return await interaction.response.send_message(
                "❌ Tylko Zarząd Federacji może zatwierdzić wniosek.", ephemeral=True)

        await interaction.response.defer()
        app = database.get_application(self.app_id)
        if not app or app.get("status") != "PENDING":
            return await interaction.followup.send("❌ Ten wniosek jest już zamknięty.", ephemeral=True)

        app_type = app.get("type")
        guild = interaction.guild
        kom_channel = guild.get_channel(CHANNEL_KOMUNIKATY_ID)

        # ─── REJESTRACJA KLUBU ───
        if app_type == "REJESTRACJA_KLUBU":
            skrot = clean_tag(app.get("club_tag"))
            nazwa = app.get("club_name")
            base_role = guild.get_role(ROLA_WZORZEC_ID)

            # Rola Zarządu kopiuje uprawnienia wzorca, Zawodnik – minimalne
            board_perms = base_role.permissions if base_role else discord.Permissions.none()
            player_perms = discord.Permissions.none()
            hoist = base_role.hoist if base_role else False

            r_zarzad = await guild.create_role(
                name=f"⚽・{skrot} - Zarząd", permissions=board_perms, hoist=hoist)
            r_zawod = await guild.create_role(
                name=f"⚽・{skrot} - Zawodnik", permissions=player_perms, hoist=False)

            founder_ids = extract_ids(app.get("founder_txt", ""))
            board_ids = extract_ids(app.get("board_txt", ""))
            applicant_id = app.get("applicant_id")
            osoby_zarzad = set(founder_ids + board_ids)
            if applicant_id:
                osoby_zarzad.add(applicant_id)

            for uid in osoby_zarzad:
                member = guild.get_member(uid)
                if member:
                    try: await member.add_roles(r_zarzad)
                    except Exception as e: print(f"[Fed] Błąd nadania roli zarządu {uid}: {e}")

            database.add_club(
                tag=skrot, name=nazwa,
                role_board_id=r_zarzad.id, role_player_id=r_zawod.id,
                reprezentant_dc=applicant_id,
                founder_txt=app.get("founder_txt", ""),
                board_txt=app.get("board_txt", ""),
                board_ids=list(osoby_zarzad)
            )
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ Zaakceptowano: {nazwa}"
            embed.add_field(name="Decyzja Federacji",
                            value=f"Zatwierdzono przez {interaction.user.mention}. Utworzono role klubowe.",
                            inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                await kom_channel.send(
                    f"📢 **NOWY KLUB!** Zespół **{nazwa}** (`{skrot}`) został zarejestrowany!",
                    allowed_mentions=discord.AllowedMentions.none()
                )

        # ─── PODPISANIE GRACZA ───
        elif app_type == "PODPISANIE":
            target_club = clean_tag(app.get("target_club"))
            if database.get_club_player_count(target_club) >= MAX_PLAYERS_PER_CLUB:
                return await interaction.followup.send(
                    f"❌ Klub `{target_club}` osiągnął limit zawodników ({MAX_PLAYERS_PER_CLUB}/{MAX_PLAYERS_PER_CLUB})!",
                    ephemeral=True)

            gracz_name = app.get("player_name")
            player_dc_id = app.get("player_discord_id")
            c_info = database.get_club(target_club)

            if player_dc_id:
                member = guild.get_member(player_dc_id)
                if member and c_info:
                    r_zaw = guild.get_role(c_info.get("role_player_id"))
                    if r_zaw:
                        try: await member.add_roles(r_zaw)
                        except Exception as e: print(f"[Fed] Błąd nadania roli zawodnika: {e}")
                # Usuń z giełdy wolnych agentów
                database.remove_free_agent(player_dc_id)

            database.add_or_update_player(
                name=gracz_name, discord_id=player_dc_id,
                club_tag=target_club, parent_club_tag=target_club,
                clause=app.get("clause", "Brak"), contract_type="BEZ_KLUBU",
                expires_at=app.get("expires_at")
            )
            database.add_transfer_history(
                player_name=gracz_name, player_discord_id=player_dc_id,
                from_club=None, to_club=target_club,
                transfer_type="BEZ_KLUBU", amount=None
            )
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ SFINALIZOWANO PODPISANIE: {gracz_name}"
            for i, f in enumerate(embed.fields):
                if f.name == "Status":
                    embed.set_field_at(i, name="Status",
                                       value=f"✅ Zatwierdzono przez Federację ({interaction.user.mention})",
                                       inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                c_nazwa = c_info.get("name", target_club) if c_info else target_club
                await kom_channel.send(
                    f"📢 **OFICJALNIE:** Zawodnik **{gracz_name}** dołącza do **{c_nazwa}** (`{target_club}`)!\n"
                    f"> Ważność umowy: `{app.get('expires_at')}` | Klauzula: `{app.get('clause')}`",
                    allowed_mentions=discord.AllowedMentions.none()
                )

            # DM do gracza
            if player_dc_id:
                await send_dm(interaction.client, player_dc_id,
                              f"📄 **Twój kontrakt z klubem `{target_club}` został oficjalnie zatwierdzony!**\n"
                              f"> Ważność: `{app.get('expires_at')}` | Klauzula: `{app.get('clause')}`")

        # ─── TRANSFER ───
        elif app_type == "TRANSFER":
            target_club = clean_tag(app.get("target_club"))
            source_club = clean_tag(app.get("source_club"))

            if database.get_club_player_count(target_club) >= MAX_PLAYERS_PER_CLUB:
                return await interaction.followup.send(
                    f"❌ Klub kupujący `{target_club}` osiągnął limit zawodników ({MAX_PLAYERS_PER_CLUB}/{MAX_PLAYERS_PER_CLUB})!",
                    ephemeral=True)

            gracz_name = app.get("player_name")
            player_dc_id = app.get("player_discord_id")
            c_target = database.get_club(target_club)
            c_source = database.get_club(source_club)

            if player_dc_id:
                member = guild.get_member(player_dc_id)
                if member:
                    if c_source:
                        r_old = guild.get_role(c_source.get("role_player_id"))
                        if r_old:
                            try: await member.remove_roles(r_old)
                            except Exception as e: print(f"[Fed] Błąd usunięcia roli: {e}")
                    if c_target:
                        r_new = guild.get_role(c_target.get("role_player_id"))
                        if r_new:
                            try: await member.add_roles(r_new)
                            except Exception as e: print(f"[Fed] Błąd nadania roli: {e}")

            database.add_or_update_player(
                name=gracz_name, discord_id=player_dc_id,
                club_tag=target_club, parent_club_tag=target_club,
                clause=app.get("clause", "Brak"), contract_type="TRANSFER",
                expires_at=app.get("expires_at")
            )
            transfer_type = "WYKUP" if not app.get("needs_source_club_agree") else "TRANSFER"
            database.add_transfer_history(
                player_name=gracz_name, player_discord_id=player_dc_id,
                from_club=source_club, to_club=target_club,
                transfer_type=transfer_type, amount=app.get("amount")
            )
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ SFINALIZOWANO TRANSFER: {gracz_name}"
            for i, f in enumerate(embed.fields):
                if f.name == "Status":
                    embed.set_field_at(i, name="Status",
                                       value=f"✅ Zaakceptowano przez Federację ({interaction.user.mention})",
                                       inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                t_nazwa = c_target.get("name", target_club) if c_target else target_club
                hype = "🔥🚨 **BOMBA TRANSFEROWA!**" if transfer_type == "WYKUP" else "📢 **OFICJALNIE:**"
                await kom_channel.send(
                    f"{hype} Zawodnik **{gracz_name}** przechodzi do drużyny **{t_nazwa}** (`{target_club}`)!\n"
                    f"> Kwota: `{app.get('amount')}` | Nowa klauzula: `{app.get('clause')}` | Umowa do: `{app.get('expires_at')}`",
                    allowed_mentions=discord.AllowedMentions.none()
                )

            if player_dc_id:
                await send_dm(interaction.client, player_dc_id,
                              f"📄 **Twój transfer do klubu `{target_club}` został oficjalnie zatwierdzony!**\n"
                              f"> Nowa umowa do: `{app.get('expires_at')}` | Klauzula: `{app.get('clause')}`")

        # ─── WYPOŻYCZENIE ───
        elif app_type == "WYPOZYCZENIE":
            target_club = clean_tag(app.get("target_club"))
            source_club = clean_tag(app.get("source_club"))

            if database.get_club_player_count(target_club) >= MAX_PLAYERS_PER_CLUB:
                return await interaction.followup.send(
                    f"❌ Klub przyjmujący `{target_club}` osiągnął limit zawodników ({MAX_PLAYERS_PER_CLUB}/{MAX_PLAYERS_PER_CLUB})!",
                    ephemeral=True)

            gracz_name = app.get("player_name")
            player_dc_id = app.get("player_discord_id")
            c_target = database.get_club(target_club)
            c_source = database.get_club(source_club)

            # Pobierz datę macierzystego kontraktu PRZED wypożyczeniem
            existing_player = database.get_player(gracz_name)
            if not existing_player and player_dc_id:
                existing_player = database.get_player_by_discord_id(player_dc_id)
            parent_expires = existing_player.get("expires_at") if existing_player else None

            if player_dc_id:
                member = guild.get_member(player_dc_id)
                if member:
                    if c_source:
                        r_old = guild.get_role(c_source.get("role_player_id"))
                        if r_old:
                            try: await member.remove_roles(r_old)
                            except Exception as e: print(f"[Fed] Błąd usunięcia roli: {e}")
                    if c_target:
                        r_new = guild.get_role(c_target.get("role_player_id"))
                        if r_new:
                            try: await member.add_roles(r_new)
                            except Exception as e: print(f"[Fed] Błąd nadania roli: {e}")

            database.add_or_update_player(
                name=gracz_name, discord_id=player_dc_id,
                club_tag=target_club, parent_club_tag=source_club,
                clause="Bez zmian", contract_type="WYPOZYCZENIE",
                expires_at=app.get("expires_at"),
                parent_contract_expires_at=parent_expires
            )
            database.add_transfer_history(
                player_name=gracz_name, player_discord_id=player_dc_id,
                from_club=source_club, to_club=target_club,
                transfer_type="WYPOZYCZENIE", amount=app.get("amount")
            )
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ SFINALIZOWANO WYPOŻYCZENIE: {gracz_name}"
            for i, f in enumerate(embed.fields):
                if f.name == "Status":
                    embed.set_field_at(i, name="Status",
                                       value=f"✅ Zaakceptowano przez Federację ({interaction.user.mention})",
                                       inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                t_nazwa = c_target.get("name", target_club) if c_target else target_club
                await kom_channel.send(
                    f"📢 **OFICJALNIE:** Zawodnik **{gracz_name}** wypożyczony do **{t_nazwa}** (`{target_club}`)!\n"
                    f"> Koniec wypożyczenia: `{app.get('expires_at')}` | Opłata: `{app.get('amount')}`",
                    allowed_mentions=discord.AllowedMentions.none()
                )

            if player_dc_id:
                await send_dm(interaction.client, player_dc_id,
                              f"📄 **Twoje wypożyczenie do klubu `{target_club}` zostało oficjalnie zatwierdzone!**\n"
                              f"> Koniec wypożyczenia: `{app.get('expires_at')}`")

        # ─── Archiwizacja wątku po akceptacji ───
        thread = interaction.channel
        if isinstance(thread, discord.Thread):
            try:
                await thread.edit(locked=True, archived=True)
            except Exception as e:
                print(f"[ForumView] Błąd archiwizacji wątku po akceptacji: {e}")

    async def cb_fed_reject(self, interaction: discord.Interaction):
        if not is_federation(interaction.user):
            return await interaction.response.send_message(
                "❌ Tylko Zarząd Federacji może odrzucić wniosek.", ephemeral=True)

        await interaction.response.defer()
        app = database.get_application(self.app_id)
        if not app or app.get("status") != "PENDING":
            return await interaction.followup.send("❌ Ten wniosek jest już zamknięty.", ephemeral=True)

        database.set_application_status(self.app_id, "REJECTED",
                                         rejected_by=f"Federacja ({interaction.user.mention})")

        embed = interaction.message.embeds[0]
        embed.color = 0xe74c3c
        old_title = embed.title or "Wniosek"
        embed.title = f"❌ ODRZUCONO: {old_title}"
        embed.add_field(name="Decyzja Federacji",
                        value=f"Wniosek odrzucony przez {interaction.user.mention}.",
                        inline=False)
        await interaction.message.edit(embed=embed, view=None)

        thread = interaction.channel
        if isinstance(thread, discord.Thread):
            try:
                await thread.edit(locked=True, archived=True)
            except Exception as e:
                print(f"[ForumView] Błąd archiwizacji wątku po odrzuceniu: {e}")
