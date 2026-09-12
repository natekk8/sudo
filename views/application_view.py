import discord
from discord import ui
import database
from config import ROLE_FEDERACJA_ID, ROLA_WZORZEC_ID, CHANNEL_KOMUNIKATY_ID, MAX_PLAYERS_PER_CLUB
from utils.helpers import is_federation, is_club_board_or_owner, extract_ids, clean_tag

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

        # 1. Zgoda gracza (tylko jeśli gracz ma konto Discord)
        if app.get("needs_player_agree"):
            if app.get("player_agreed"):
                btn_player = ui.Button(
                    label="Zgoda gracza",
                    style=discord.ButtonStyle.green,
                    emoji="✅",
                    disabled=True,
                    custom_id=f"app:{self.app_id}:p_agree"
                )
            else:
                btn_player = ui.Button(
                    label="Zgoda gracza",
                    style=discord.ButtonStyle.primary,
                    emoji="✍️",
                    custom_id=f"app:{self.app_id}:p_agree"
                )
                btn_player.callback = self.cb_player_agree
            self.add_item(btn_player)

        # 2. Zgoda klubu kupującego / przyjmującego (tylko jeśli zarząd ma DC)
        if app.get("needs_target_club_agree"):
            target_label = "Zgoda klubu" if app_type == "PODPISANIE" else "Zgoda kupującego"
            if app_type == "WYPOZYCZENIE":
                target_label = "Zgoda przyjmującego"

            if app.get("target_club_agreed"):
                btn_target = ui.Button(
                    label=target_label,
                    style=discord.ButtonStyle.green,
                    emoji="✅",
                    disabled=True,
                    custom_id=f"app:{self.app_id}:t_agree"
                )
            else:
                btn_target = ui.Button(
                    label=target_label,
                    style=discord.ButtonStyle.secondary,
                    emoji="🤝",
                    custom_id=f"app:{self.app_id}:t_agree"
                )
                btn_target.callback = self.cb_target_agree
            self.add_item(btn_target)

        # 3. Zgoda klubu sprzedającego / oddającego (tylko w transferze/wypożyczeniu gdy wymagana i zarząd ma DC)
        if app.get("needs_source_club_agree"):
            source_label = "Zgoda sprzedającego" if app_type == "TRANSFER" else "Zgoda oddającego"
            if app.get("source_club_agreed"):
                btn_source = ui.Button(
                    label=source_label,
                    style=discord.ButtonStyle.green,
                    emoji="✅",
                    disabled=True,
                    custom_id=f"app:{self.app_id}:s_agree"
                )
            else:
                btn_source = ui.Button(
                    label=source_label,
                    style=discord.ButtonStyle.secondary,
                    emoji="🤝",
                    custom_id=f"app:{self.app_id}:s_agree"
                )
                btn_source.callback = self.cb_source_agree
            self.add_item(btn_source)

        # 4. Przyciski Federacji: Akceptuj i Odrzuć (zawsze obecne)
        btn_accept = ui.Button(
            label="Akceptuj",
            style=discord.ButtonStyle.green,
            emoji="✅",
            custom_id=f"app:{self.app_id}:fed_accept"
        )
        btn_accept.callback = self.cb_fed_accept
        self.add_item(btn_accept)

        btn_reject = ui.Button(
            label="Odrzuć",
            style=discord.ButtonStyle.red,
            emoji="❌",
            custom_id=f"app:{self.app_id}:fed_reject"
        )
        btn_reject.callback = self.cb_fed_reject
        self.add_item(btn_reject)

    def _update_embed_status(self, embed: discord.Embed, app: dict) -> discord.Embed:
        app_type = app.get("type")
        if app_type == "REJESTRACJA_KLUBU":
            return embed

        status_lines = []

        # Gracz
        if app.get("needs_player_agree"):
            p_st = "✅ Udzielono" if app.get("player_agreed") else "⏳ Oczekuje"
            status_lines.append(f"• Zawodnik: {p_st}")
        else:
            status_lines.append("• Zawodnik: ℹ️ Brak konta Discord (kontakt poza DC)")

        # Kupujący / Przyjmujący
        target_name = app.get('target_club', '')
        if app.get("needs_target_club_agree"):
            t_st = "✅ Zgoda udzielona" if app.get("target_club_agreed") else "⏳ Oczekuje"
            status_lines.append(f"• Klub `{target_name}`: {t_st}")
        elif target_name:
            status_lines.append(f"• Klub `{target_name}`: ℹ️ Brak oznaczonych kont zarządu")

        # Sprzedający / Oddający
        if app_type in ("TRANSFER", "WYPOZYCZENIE"):
            source_name = app.get('source_club', '')
            if app.get("needs_source_club_agree"):
                s_st = "✅ Zgoda udzielona" if app.get("source_club_agreed") else "⏳ Oczekuje"
                status_lines.append(f"• Klub `{source_name}`: {s_st}")
            elif not app.get("needs_source_club_agree") and app_type == "TRANSFER":
                status_lines.append(f"• Klub `{source_name}`: ⚡ Wykup klauzulowy (zgoda zbędna)")
            elif source_name:
                status_lines.append(f"• Klub `{source_name}`: ℹ️ Brak oznaczonych kont zarządu")

        status_lines.append("• Zarząd Federacji: ⏳ Oczekuje na decyzję")
        full_status_text = "\n".join(status_lines)

        for i, field in enumerate(embed.fields):
            if field.name == "Status":
                embed.set_field_at(i, name="Status", value=full_status_text, inline=False)
                return embed

        embed.add_field(name="Status", value=full_status_text, inline=False)
        return embed

    # ==================== CALLBACKS ====================

    async def cb_player_agree(self, interaction: discord.Interaction):
        app = database.get_application(self.app_id)
        if not app:
            return await interaction.response.send_message("❌ Wniosek nie istnieje!", ephemeral=True)

        if interaction.user.id != app.get("player_discord_id"):
            return await interaction.response.send_message("❌ Tylko wskazany zawodnik może kliknąć ten przycisk!", ephemeral=True)

        database.set_application_agreement(self.app_id, "player", True)
        app = database.get_application(self.app_id)
        self._build_buttons()

        embed = interaction.message.embeds[0]
        embed = self._update_embed_status(embed, app)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("✅ Złożono podpis zawodnika.", ephemeral=True)

    async def cb_target_agree(self, interaction: discord.Interaction):
        app = database.get_application(self.app_id)
        if not app:
            return await interaction.response.send_message("❌ Wniosek nie istnieje!", ephemeral=True)

        target_club = app.get("target_club")
        if not is_club_board_or_owner(interaction.user, target_club):
            return await interaction.response.send_message(f"❌ Tylko Zarząd/Właściciel klubu `{target_club}` może wyrazić zgodę!", ephemeral=True)

        database.set_application_agreement(self.app_id, "target_club", True)
        app = database.get_application(self.app_id)
        self._build_buttons()

        embed = interaction.message.embeds[0]
        embed = self._update_embed_status(embed, app)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("✅ Udzielono zgody klubu.", ephemeral=True)

    async def cb_source_agree(self, interaction: discord.Interaction):
        app = database.get_application(self.app_id)
        if not app:
            return await interaction.response.send_message("❌ Wniosek nie istnieje!", ephemeral=True)

        source_club = app.get("source_club")
        if not is_club_board_or_owner(interaction.user, source_club):
            return await interaction.response.send_message(f"❌ Tylko Zarząd/Właściciel klubu `{source_club}` może wyrazić zgodę!", ephemeral=True)

        database.set_application_agreement(self.app_id, "source_club", True)
        app = database.get_application(self.app_id)
        self._build_buttons()

        embed = interaction.message.embeds[0]
        embed = self._update_embed_status(embed, app)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("✅ Udzielono zgody klubu oddającego/sprzedającego.", ephemeral=True)

    async def cb_fed_accept(self, interaction: discord.Interaction):
        if not is_federation(interaction.user):
            return await interaction.response.send_message("❌ Brak uprawnień! Tylko Zarząd Federacji może zatwierdzić wniosek.", ephemeral=True)

        await interaction.response.defer()
        app = database.get_application(self.app_id)
        if not app or app.get("status") != "PENDING":
            return await interaction.followup.send("❌ Ten wniosek został już przetworzony!", ephemeral=True)

        app_type = app.get("type")
        guild = interaction.guild
        kom_channel = guild.get_channel(CHANNEL_KOMUNIKATY_ID)

        # ----------------- REJESTRACJA KLUBU -----------------
        if app_type == "REJESTRACJA_KLUBU":
            skrot = clean_tag(app.get("club_tag"))
            nazwa = app.get("club_name")
            base_role = guild.get_role(ROLA_WZORZEC_ID)

            perms = base_role.permissions if base_role else discord.Permissions.none()
            hoist = base_role.hoist if base_role else False

            r_zarzad = await guild.create_role(name=f"⚽・{skrot} - Zarząd", permissions=perms, hoist=hoist)
            r_zawod = await guild.create_role(name=f"⚽・{skrot} - Zawodnik", permissions=perms, hoist=hoist)

            founder_ids = extract_ids(app.get("founder_txt", ""))
            board_ids = extract_ids(app.get("board_txt", ""))
            applicant_id = app.get("applicant_id")

            osoby_zarzad = set(founder_ids + board_ids)
            if applicant_id:
                osoby_zarzad.add(applicant_id)

            for uid in osoby_zarzad:
                member = guild.get_member(uid)
                if member:
                    try:
                        await member.add_roles(r_zarzad)
                    except Exception as e:
                        print(f"Błąd nadawania roli zarządu dla {uid}: {e}")

            database.add_club(
                tag=skrot,
                name=nazwa,
                role_board_id=r_zarzad.id,
                role_player_id=r_zawod.id,
                reprezentant_dc=applicant_id,
                founder_txt=app.get("founder_txt", ""),
                board_txt=app.get("board_txt", ""),
                board_ids=list(osoby_zarzad)
            )

            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ Zaakceptowano: {nazwa}"
            embed.add_field(name="Decyzja Federacji", value=f"Zatwierdzono przez {interaction.user.mention}. Utworzono role klubowe.", inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                await kom_channel.send(f"📢 **NOWY KLUB!** Zespół **{nazwa}** (`{skrot}`) został zarejestrowany!")

        # ----------------- PODPISANIE GRACZA -----------------
        elif app_type == "PODPISANIE":
            target_club = clean_tag(app.get("target_club"))
            current_players = database.get_club_player_count(target_club)
            if current_players >= MAX_PLAYERS_PER_CLUB:
                return await interaction.followup.send(
                    f"❌ Klub `{target_club}` posiada już maksymalną liczbę zawodników ({current_players}/{MAX_PLAYERS_PER_CLUB})! Nie można podpisać gracza.",
                    ephemeral=True
                )

            gracz_name = app.get("player_name")
            player_dc_id = app.get("player_discord_id")

            c_info = database.get_club(target_club)
            if c_info and player_dc_id:
                member = guild.get_member(player_dc_id)
                if member:
                    r_zaw = guild.get_role(c_info.get("role_player_id"))
                    if r_zaw:
                        try:
                            await member.add_roles(r_zaw)
                        except Exception as e:
                            print(f"Błąd nadania roli: {e}")

            database.add_or_update_player(
                name=gracz_name,
                discord_id=player_dc_id,
                club_tag=target_club,
                parent_club_tag=target_club,
                clause=app.get("clause", "Brak"),
                contract_type="BEZ_KLUBU",
                expires_at=app.get("expires_at")
            )
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ SFINALIZOWANO PODPISANIE: {gracz_name}"
            for i, f in enumerate(embed.fields):
                if f.name == "Status":
                    embed.set_field_at(i, name="Status", value=f"✅ Zatwierdzono przez Federację ({interaction.user.mention})", inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                c_nazwa = c_info.get("nazwa", target_club) if c_info else target_club
                await kom_channel.send(
                    f"📢 **OFICJALNIE:** Zawodnik **{gracz_name}** dołącza do **{c_nazwa}**!\n"
                    f"> Ważność umowy: `{app.get('expires_at')}` | Klauzula: `{app.get('clause')}`"
                )

        # ----------------- TRANSFER -----------------
        elif app_type == "TRANSFER":
            target_club = clean_tag(app.get("target_club"))
            source_club = clean_tag(app.get("source_club"))

            current_players = database.get_club_player_count(target_club)
            if current_players >= MAX_PLAYERS_PER_CLUB:
                return await interaction.followup.send(
                    f"❌ Klub kupujący `{target_club}` posiada już maksymalną liczbę zawodników ({current_players}/{MAX_PLAYERS_PER_CLUB})! Nie można zatwierdzić transferu.",
                    ephemeral=True
                )

            gracz_name = app.get("player_name")
            player_dc_id = app.get("player_discord_id")

            # Przenoszenie ról
            c_target = database.get_club(target_club)
            c_source = database.get_club(source_club)

            if player_dc_id:
                member = guild.get_member(player_dc_id)
                if member:
                    if c_source:
                        r_old = guild.get_role(c_source.get("role_player_id"))
                        if r_old:
                            try: await member.remove_roles(r_old)
                            except Exception as e: print(e)
                    if c_target:
                        r_new = guild.get_role(c_target.get("role_player_id"))
                        if r_new:
                            try: await member.add_roles(r_new)
                            except Exception as e: print(e)

            database.add_or_update_player(
                name=gracz_name,
                discord_id=player_dc_id,
                club_tag=target_club,
                parent_club_tag=target_club,
                clause=app.get("clause", "Brak"),
                contract_type="TRANSFER",
                expires_at=app.get("expires_at")
            )
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ SFINALIZOWANO TRANSFER: {gracz_name}"
            for i, f in enumerate(embed.fields):
                if f.name == "Status":
                    embed.set_field_at(i, name="Status", value=f"✅ Zaakceptowano przez Federację ({interaction.user.mention})", inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                t_nazwa = c_target.get("name", target_club) if c_target else target_club
                await kom_channel.send(
                    f"📢 **OFICJALNIE:** Zawodnik **{gracz_name}** przechodzi do drużyny **{t_nazwa}**!\n"
                    f"> Kwota: `{app.get('amount')}` | Nowa Klauzula: `{app.get('clause')}` | Umowa do: `{app.get('expires_at')}`"
                )

            # AUTOMATYCZNY KANAŁ PO TRANSFERZE DO REJESTRACJI KONTRAKTU
            try:
                ticket_id = database.get_next_ticket_id()
                safe_name = "".join(c for c in gracz_name if c.isalnum() or c in ("-", "_"))[:12]
                ch_name = f"kontrakt-{target_club.lower()}-{safe_name}-{ticket_id}"

                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                    guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
                }

                # Uprawnienia dla zgłaszającego (kupujący)
                app_applicant = guild.get_member(app.get("applicant_id"))
                if app_applicant:
                    overwrites[app_applicant] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

                # Uprawnienia dla gracza
                if player_dc_id:
                    p_member = guild.get_member(player_dc_id)
                    if p_member:
                        overwrites[p_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

                # Uprawnienia dla federacji
                r_fed = guild.get_role(ROLE_FEDERACJA_ID)
                if r_fed:
                    overwrites[r_fed] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

                # Uprawnienia dla zarządu klubu kupującego
                if c_target:
                    r_board = guild.get_role(c_target.get("role_board_id"))
                    if r_board:
                        overwrites[r_board] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

                contract_channel = await guild.create_text_channel(name=ch_name, overwrites=overwrites)
                p_mention = f"<@{player_dc_id}>" if player_dc_id else gracz_name
                await contract_channel.send(
                    f"📄 **KANAŁ REJESTRACJI KONTRAKTU PO TRANSFERZE**\n"
                    f"> Zawodnik: **{p_mention}**\n"
                    f"> Nowy klub: **`{target_club}`**\n\n"
                    f"Zarząd kupujący oraz zawodnik i Federacja mogą tutaj ustalić i zapisać ostateczne warunki umowy."
                )
            except Exception as e:
                print(f"Błąd tworzenia automatycznego kanału kontraktu po transferze: {e}")

        # ----------------- WYPOŻYCZENIE -----------------
        elif app_type == "WYPOZYCZENIE":
            target_club = clean_tag(app.get("target_club"))
            source_club = clean_tag(app.get("source_club"))

            current_players = database.get_club_player_count(target_club)
            if current_players >= MAX_PLAYERS_PER_CLUB:
                return await interaction.followup.send(
                    f"❌ Klub przyjmujący `{target_club}` posiada już maksymalną liczbę zawodników ({current_players}/{MAX_PLAYERS_PER_CLUB})! Nie można zatwierdzić wypożyczenia.",
                    ephemeral=True
                )

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
                            except Exception as e: print(e)
                    if c_target:
                        r_new = guild.get_role(c_target.get("role_player_id"))
                        if r_new:
                            try: await member.add_roles(r_new)
                            except Exception as e: print(e)

            database.add_or_update_player(
                name=gracz_name,
                discord_id=player_dc_id,
                club_tag=target_club,
                parent_club_tag=source_club,
                clause="Bez zmian",
                contract_type="WYPOZYCZENIE",
                expires_at=app.get("expires_at")
            )
            database.set_application_status(self.app_id, "ACCEPTED")

            embed = interaction.message.embeds[0]
            embed.color = 0x2ecc71
            embed.title = f"✅ SFINALIZOWANO WYPOŻYCZENIE: {gracz_name}"
            for i, f in enumerate(embed.fields):
                if f.name == "Status":
                    embed.set_field_at(i, name="Status", value=f"✅ Zaakceptowano przez Federację ({interaction.user.mention})", inline=False)
            await interaction.message.edit(embed=embed, view=None)

            if kom_channel:
                t_nazwa = c_target.get("name", target_club) if c_target else target_club
                await kom_channel.send(
                    f"📢 **OFICJALNIE:** Zawodnik **{gracz_name}** został wypożyczony do **{t_nazwa}**!\n"
                    f"> Koniec wypożyczenia: `{app.get('expires_at')}` | Opłata: `{app.get('amount')}`"
                )

    async def cb_fed_reject(self, interaction: discord.Interaction):
        if not is_federation(interaction.user):
            return await interaction.response.send_message("❌ Brak uprawnień! Tylko Zarząd Federacji może odrzucić wniosek.", ephemeral=True)

        await interaction.response.defer()
        app = database.get_application(self.app_id)
        if not app or app.get("status") != "PENDING":
            return await interaction.followup.send("❌ Ten wniosek został już przetworzony!", ephemeral=True)

        database.set_application_status(self.app_id, "REJECTED")

        embed = interaction.message.embeds[0]
        embed.color = 0xe74c3c
        embed.title = f"❌ ODRZUCONO: {embed.title.replace('🏛️ Podsumowanie: ', '').replace('📄 Podpisanie Gracza: ', '').replace('🤝 Transfer: ', '').replace('🔥 Wykup: ', '').replace('⏱️ Wypożyczenie: ', '')}"
        embed.add_field(name="Decyzja Federacji", value=f"Wniosek został odrzucony przez {interaction.user.mention}.", inline=False)
        await interaction.message.edit(embed=embed, view=None)
