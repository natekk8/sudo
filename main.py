import os
import json
import discord
from discord.ext import commands
from discord import ui
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# KONFIGURACJA ID
# ==========================================
ROLE_FEDERACJA_ID = 1545869517459161092   
ROLA_WZORZEC_ID = 1545869511318708244  # Rola do klonowania

CHANNEL_FORUM_ID = 1548260165134852157          
CHANNEL_KOMUNIKATY_ID = 1548260354264539196     

DB_FILE = "baza_ligi.json"

def load_db():
    if not os.path.exists(DB_FILE):
        return {"kluby": {}, "zawodnicy": {}}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def is_federation(member):
    return any(r.id == ROLE_FEDERACJA_ID for r in member.roles)

def has_club_board_role(member, club_tag, db):
    if is_federation(member): return True
    if club_tag not in db["kluby"]: return False
    return any(r.id == db["kluby"][club_tag].get("rola_zarzad") for r in member.roles)

def clean_tag(tag: str):
    return tag.strip().upper()

async def ping_reprezentantow(thread, kup, sprzed=None):
    db = load_db()
    ids = []
    if kup in db["kluby"]: ids.append(db["kluby"][kup].get("reprezentant_dc"))
    if sprzed and sprzed in db["kluby"]: ids.append(db["kluby"][sprzed].get("reprezentant_dc"))
    ids = [uid for uid in set(ids) if uid]

    if ids:
        mentions = " ".join([f"<@{uid}>" for uid in ids])
        await thread.send(f"🔔 **Wymagana uwaga:** {mentions}\n> Zarządzie, jeśli gracz posiada Discord, oznaczcie go w tym wątku, aby mógł kliknąć przycisk podpisu osobistego.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
# MODALE (FORMULARZE)
# ==========================================
class ModalRejestracjaKlubu(ui.Modal, title="📝 Rejestracja Klubu"):
    nazwa = ui.TextInput(label="Pełna nazwa klubu", max_length=60)
    skrot = ui.TextInput(label="Skrót (dokładnie 3 litery)", min_length=3, max_length=3)
    zalozyciel = ui.TextInput(label="Główny Założyciel (Nick z gry / Imię)")
    zarzad = ui.TextInput(label="Pozostały Zarząd (Opcjonalnie)", style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
        tag = clean_tag(self.skrot.value)
        db = load_db()

        if tag in db["kluby"]:
            return await interaction.response.send_message(f"❌ Klub `{tag}` już istnieje!", ephemeral=True)

        embed = discord.Embed(title=f"🏛️ Wniosek o Rejestrację: {self.nazwa.value}", color=0x2b2d31)
        embed.add_field(name="📌 Skrót", value=f"`{tag}`", inline=True)
        embed.add_field(name="👑 Założyciel", value=self.zalozyciel.value, inline=True)
        embed.add_field(name="👥 Zarząd", value=self.zarzad.value or "Brak", inline=False)
        embed.add_field(name="📡 Reprezentant na Discordzie", value=interaction.user.mention, inline=False)

        view = WidokZatwierdzeniaKlubu(nazwa=self.nazwa.value, skrot=tag, zalozyciel_txt=self.zalozyciel.value, rep_id=interaction.user.id)
        thread = await forum.create_thread(name=f"[{tag}] {self.nazwa.value}", embed=embed, view=view)
        await interaction.response.send_message(f"✅ Wniosek wysłany: {thread.thread.mention}", ephemeral=True)


class ModalPodpisGracza(ui.Modal, title="👤 Podpisanie Gracza (Bez Klubu)"):
    zawodnik = ui.TextInput(label="Zawodnik (Nick z gry / Imię)")
    klub_kup = ui.TextInput(label="Twój Klub (Skrót)", min_length=3, max_length=3)
    czas = ui.TextInput(label="Czas trwania kontraktu")
    klauzula = ui.TextInput(label="Klauzula (Zostaw puste by pominąć)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        forum, db, kup = interaction.guild.get_channel(CHANNEL_FORUM_ID), load_db(), clean_tag(self.klub_kup.value)
        
        if not has_club_board_role(interaction.user, kup, db):
            return await interaction.response.send_message(f"❌ Odmowa dostępu: Nie jesteś w Zarządzie `{kup}`!", ephemeral=True)

        klauz_val = self.klauzula.value.strip() if self.klauzula.value else "Brak"
        embed = discord.Embed(title=f"📄 Podpisanie Gracza: {self.zawodnik.value}", color=0x3498db)
        embed.add_field(name="Kupujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Czas", value=self.czas.value, inline=True)
        embed.add_field(name="Klauzula", value=f"`{klauz_val}`", inline=True)
        embed.add_field(name="Status", value="⏳ Oczekuje na podpis (Gracz lub Zarząd).", inline=False)

        view = WidokPodpisu(gracz=self.zawodnik.value, kup=kup, sprzed=None, kwota="0", klauz=klauz_val, wym_sprzed=False, typ="BEZ_KLUBU")
        thread = await forum.create_thread(name=f"[KONTRAKT] {self.zawodnik.value} ➡️ {kup}", embed=embed, view=view)
        await ping_reprezentantow(thread.thread, kup)
        await interaction.response.send_message("✅ Wniosek utworzony.", ephemeral=True)


class ModalTransfer(ui.Modal, title="🤝 Wniosek Transferowy"):
    zawodnik = ui.TextInput(label="Zawodnik (Nick z gry / Imię)")
    klub_kup = ui.TextInput(label="Twój Klub Kupujący (Skrót)", min_length=3, max_length=3)
    klub_sprzed = ui.TextInput(label="Klub Sprzedający (Skrót)", min_length=3, max_length=3)
    kwota = ui.TextInput(label="Kwota Transferu")
    klauzula = ui.TextInput(label="Nowa Klauzula (Zostaw puste by pominąć)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        forum, db, kup, sprzed = interaction.guild.get_channel(CHANNEL_FORUM_ID), load_db(), clean_tag(self.klub_kup.value), clean_tag(self.klub_sprzed.value)

        if not has_club_board_role(interaction.user, kup, db):
            return await interaction.response.send_message(f"❌ Odmowa dostępu: Nie jesteś w Zarządzie `{kup}`!", ephemeral=True)
        if sprzed not in db["kluby"]:
            return await interaction.response.send_message(f"❌ Klub `{sprzed}` nie istnieje!", ephemeral=True)

        # Sprawdzenie klauzuli starego klubu
        czy_klauzula = False
        dane_gracza = db["zawodnicy"].get(self.zawodnik.value)
        if dane_gracza and dane_gracza.get("klauzula") and dane_gracza["klauzula"].lower() != "brak":
            try:
                if int("".join(filter(str.isdigit, self.kwota.value))) >= int("".join(filter(str.isdigit, str(dane_gracza["klauzula"])))):
                    czy_klauzula = True
            except: pass

        klauz_val = self.klauzula.value.strip() if self.klauzula.value else "Brak"
        wym_sprzed = not czy_klauzula
        
        embed = discord.Embed(title=f"{'🔥 Wykup z Klauzuli' if czy_klauzula else '🤝 Transfer'}: {self.zawodnik.value}", color=0xe67e22 if czy_klauzula else 0x9b59b6)
        embed.add_field(name="Kupujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Sprzedający", value=f"`{sprzed}`", inline=True)
        embed.add_field(name="Kwota", value=f"`{self.kwota.value}`", inline=True)
        embed.add_field(name="Nowa Klauzula", value=f"`{klauz_val}`", inline=False)
        embed.add_field(name="Status", value="⚡ Zgoda starego klubu niewymagana." if czy_klauzula else "⏳ Oczekuje na zgody.", inline=False)

        view = WidokPodpisu(gracz=self.zawodnik.value, kup=kup, sprzed=sprzed, kwota=self.kwota.value, klauz=klauz_val, wym_sprzed=wym_sprzed, typ="TRANSFER")
        thread = await forum.create_thread(name=f"[{kup}] Transfer: {self.zawodnik.value}", embed=embed, view=view)
        await ping_reprezentantow(thread.thread, kup, sprzed)
        await interaction.response.send_message("✅ Wniosek utworzony.", ephemeral=True)


class ModalWypozyczenie(ui.Modal, title="⏱️ Wypożyczenie Zawodnika"):
    zawodnik = ui.TextInput(label="Zawodnik (Nick z gry / Imię)")
    klub_kup = ui.TextInput(label="Twój Klub Przyjmujący (Skrót)", min_length=3, max_length=3)
    klub_sprzed = ui.TextInput(label="Klub Oddający (Skrót)", min_length=3, max_length=3)
    czas = ui.TextInput(label="Czas trwania")
    kwota = ui.TextInput(label="Opłata za wypożyczenie (0 jeśli brak)")

    async def on_submit(self, interaction: discord.Interaction):
        forum, db, kup, sprzed = interaction.guild.get_channel(CHANNEL_FORUM_ID), load_db(), clean_tag(self.klub_kup.value), clean_tag(self.klub_sprzed.value)

        if not has_club_board_role(interaction.user, kup, db):
            return await interaction.response.send_message(f"❌ Odmowa dostępu!", ephemeral=True)
        if sprzed not in db["kluby"]:
            return await interaction.response.send_message(f"❌ Klub `{sprzed}` nie istnieje!", ephemeral=True)

        embed = discord.Embed(title=f"⏱️ Wypożyczenie: {self.zawodnik.value}", color=0x1abc9c)
        embed.add_field(name="Przyjmujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Oddający", value=f"`{sprzed}`", inline=True)
        embed.add_field(name="Opłata", value=f"`{self.kwota.value}`", inline=True)
        embed.add_field(name="Czas", value=self.czas.value, inline=False)
        embed.add_field(name="Status", value="⏳ Oczekuje na zgody.", inline=False)

        view = WidokPodpisu(gracz=self.zawodnik.value, kup=kup, sprzed=sprzed, kwota=self.kwota.value, klauz="Bez zmian", wym_sprzed=True, typ="WYPOZYCZENIE")
        thread = await forum.create_thread(name=f"[{kup}] Wypożyczenie: {self.zawodnik.value}", embed=embed, view=view)
        await ping_reprezentantow(thread.thread, kup, sprzed)
        await interaction.response.send_message("✅ Wniosek utworzony.", ephemeral=True)


# ==========================================
# WIDOKI I PRZYCISKI
# ==========================================
class WidokZatwierdzeniaKlubu(ui.View):
    def __init__(self, nazwa, skrot, zalozyciel_txt, rep_id):
        super().__init__(timeout=None)
        self.nazwa, self.skrot, self.zalozyciel_txt, self.rep_id = nazwa, skrot, zalozyciel_txt, rep_id

    @ui.button(label="Zatwierdź & Utwórz Role", style=discord.ButtonStyle.green, custom_id="btn_appr_club")
    async def zatwierdz(self, interaction: discord.Interaction, button):
        if not is_federation(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień!", ephemeral=True)
        await interaction.response.defer()

        guild = interaction.guild
        base_role = guild.get_role(ROLA_WZORZEC_ID)
        r_zarzad = await guild.create_role(name=f"⚽・{self.skrot} - Zarząd", permissions=base_role.permissions, hoist=base_role.hoist)
        r_zawod = await guild.create_role(name=f"⚽・{self.skrot} - Zawodnik", permissions=base_role.permissions, hoist=base_role.hoist)

        # Reprezentant DC automatycznie dostaje rolę zarządu nowego klubu
        member = guild.get_member(self.rep_id)
        if member: await member.add_roles(r_zarzad)

        db = load_db()
        db["kluby"][self.skrot] = {"nazwa": self.nazwa, "rola_zarzad": r_zarzad.id, "rola_zawodnik": r_zawod.id, "reprezentant_dc": self.rep_id}
        save_db(db)

        embed = interaction.message.embeds[0]
        embed.color = 0x2ecc71
        embed.title = f"✅ Zaakceptowano: {self.nazwa}"
        await interaction.message.edit(embed=embed, view=None)
        kom = interaction.guild.get_channel(CHANNEL_KOMUNIKATY_ID)
        if kom: await kom.send(f"📢 **NOWY KLUB!** Zespół **{self.nazwa}** (`{self.skrot}`) zarejestrowany!")

class WidokPodpisu(ui.View):
    def __init__(self, gracz, kup, sprzed, kwota, klauz, wym_sprzed, typ):
        super().__init__(timeout=None)
        self.gracz, self.kup, self.sprzed, self.kwota, self.klauz, self.wym_sprzed, self.typ = gracz, kup, sprzed, kwota, klauz, wym_sprzed, typ
        self.p_gracz = False
        self.p_sprzed = not wym_sprzed
        self.gracz_dc_id = None

    def odswiez(self, embed):
        t = f"• Zawodnik: {'✅ Podpisano' if self.p_gracz else '⏳ Oczekuje'}\n"
        if self.wym_sprzed: t += f"• Sprzedający (`{self.sprzed}`): {'✅ Zgoda' if self.p_sprzed else '⏳ Oczekuje'}\n"
        t += "• Federacja: ⏳ Oczekuje na weryfikację"
        for f in embed.fields:
            if f.name == "Status": f.value = t
        return embed

    @ui.button(label="✍️ Podpis Gracza", style=discord.ButtonStyle.primary, custom_id="b_gracz_os")
    async def b_gracz_os(self, interaction: discord.Interaction, button):
        self.p_gracz = True
        self.gracz_dc_id = interaction.user.id # Zapisuje fizyczne ID osoby klikającej
        for c in self.children: 
            if c.custom_id in ["b_gracz_os", "b_gracz_tel"]: c.disabled = True
        button.label = "Osobiście"
        await interaction.message.edit(embed=self.odswiez(interaction.message.embeds[0]), view=self)
        await interaction.response.send_message("Złożono podpis osobisty.")

    @ui.button(label="📞 Podpis Zastępczy Zarządu", style=discord.ButtonStyle.secondary, custom_id="b_gracz_tel")
    async def b_gracz_tel(self, interaction: discord.Interaction, button):
        if not has_club_board_role(interaction.user, self.kup, load_db()):
            return await interaction.response.send_message("❌ Tylko Zarząd kupujący może ręczyć za gracza bez Discorda!", ephemeral=True)
        self.p_gracz = True
        for c in self.children: 
            if c.custom_id in ["b_gracz_os", "b_gracz_tel"]: c.disabled = True
        button.label = "Przez Zarząd"
        await interaction.message.edit(embed=self.odswiez(interaction.message.embeds[0]), view=self)
        await interaction.response.send_message("Oświadczono zgodę zawodnika.")

    @ui.button(label="🤝 Zgoda Sprzedawcy", style=discord.ButtonStyle.secondary, custom_id="b_sprzed")
    async def b_sprzed(self, interaction: discord.Interaction, button):
        if not self.wym_sprzed: return await interaction.response.send_message("Zgoda niewymagana!", ephemeral=True)
        if not has_club_board_role(interaction.user, self.sprzed, load_db()):
            return await interaction.response.send_message(f"❌ Wymagana rola Zarządu klubu `{self.sprzed}`!", ephemeral=True)
        self.p_sprzed = True
        button.disabled = True
        button.label = "Zgoda"
        await interaction.message.edit(embed=self.odswiez(interaction.message.embeds[0]), view=self)
        await interaction.response.send_message("Udzielono zgody.")

    @ui.button(label="✅ Zatwierdź (Federacja)", style=discord.ButtonStyle.green, custom_id="b_fed")
    async def b_fed(self, interaction: discord.Interaction, button):
        if not is_federation(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień!", ephemeral=True)
        
        await interaction.response.defer()
        db = load_db()
        guild = interaction.guild

        # Przełączanie ról jeśli gracz podpisał się osobiście i mamy jego konto
        if self.gracz_dc_id:
            member = guild.get_member(self.gracz_dc_id)
            if member:
                if self.sprzed and self.sprzed in db["kluby"]:
                    old_role = guild.get_role(db["kluby"][self.sprzed].get("rola_zawodnik", 0))
                    if old_role: await member.remove_roles(old_role)
                if self.kup in db["kluby"]:
                    new_role = guild.get_role(db["kluby"][self.kup].get("rola_zawodnik", 0))
                    if new_role: await member.add_roles(new_role)

        db["zawodnicy"][self.gracz] = {"klub": self.kup, "klauzula": self.klauz}
        save_db(db)

        embed = interaction.message.embeds[0]
        embed.color = 0x2ecc71
        embed.title = f"✅ SFINALIZOWANO: {self.gracz}"
        await interaction.message.edit(embed=embed, view=None)

        kom = interaction.guild.get_channel(CHANNEL_KOMUNIKATY_ID)
        akcja = "został wypożyczony do" if self.typ == "WYPOZYCZENIE" else "dołącza do"
        if kom: await kom.send(f"📢 **OFICJALNIE:** {self.gracz} {akcja} **{db['kluby'][self.kup]['nazwa']}**!\n> Kwota: `{self.kwota}` | Klauzula: `{self.klauz}`")

# ==========================================
# GŁÓWNY PANEL STARTOWY
# ==========================================
class WidokPaneluGlownego(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @ui.button(label="Rejestracja Klubu", style=discord.ButtonStyle.primary, emoji="📝", custom_id="p_klub")
    async def b_k(self, i, b): await i.response.send_modal(ModalRejestracjaKlubu())
    @ui.button(label="Podpisanie gracza", style=discord.ButtonStyle.success, emoji="👤", custom_id="p_wolny")
    async def b_w(self, i, b): await i.response.send_modal(ModalPodpisGracza())
    @ui.button(label="Wniosek Transferowy", style=discord.ButtonStyle.secondary, emoji="🤝", custom_id="p_trans")
    async def b_t(self, i, b): await i.response.send_modal(ModalTransfer())
    @ui.button(label="Wypożyczenie", style=discord.ButtonStyle.secondary, emoji="⏱️", custom_id="p_wyp")
    async def b_wyp(self, i, b): await i.response.send_modal(ModalWypozyczenie())

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_panel(ctx):
    embed = discord.Embed(title="🏛️ Panel Federacji", color=0x2b2d31)
    await ctx.send(embed=embed, view=WidokPaneluGlownego())
    await ctx.message.delete()

bot.run(os.getenv("DISCORD_TOKEN"))
