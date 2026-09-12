import os
import json
import re
import discord
from discord.ext import commands
from discord import ui
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# KONFIGURACJA ID
# ==========================================
ROLE_FEDERACJA_ID = 1545869517459161092   
ROLA_WZORZEC_ID = 1545869511318708244  # Rola, którą bot będzie klonował dla klubów

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

def extract_ids(text: str):
    if not text: return []
    return [int(uid) for uid in re.findall(r'<@!?(\d+)>', text)]

def is_federation(member):
    return any(r.id == ROLE_FEDERACJA_ID for r in member.roles)

def has_club_board_role(member, club_tag, db):
    if is_federation(member): return True # Federacja ma uprawnienia wszędzie
    if club_tag not in db["kluby"]: return False
    board_role_id = db["kluby"][club_tag].get("rola_zarzad")
    return any(r.id == board_role_id for r in member.roles)

def clean_tag(tag: str):
    return tag.strip().upper()

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
    zalozyciel = ui.TextInput(label="Główny Założyciel (@Oznaczenie lub Imię)")

    async def on_submit(self, interaction: discord.Interaction):
        forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
        tag = clean_tag(self.skrot.value)
        db = load_db()

        if tag in db["kluby"]:
            return await interaction.response.send_message(f"❌ Klub `{tag}` już istnieje!", ephemeral=True)

        embed = discord.Embed(title=f"🏛️ Wniosek o Rejestrację: {self.nazwa.value}", color=0x2b2d31)
        embed.add_field(name="📌 Skrót", value=f"`{tag}`", inline=True)
        embed.add_field(name="👑 Założyciel", value=self.zalozyciel.value, inline=True)
        embed.add_field(name="Zgłasza", value=interaction.user.mention, inline=False)

        view = WidokZatwierdzeniaKlubu(nazwa=self.nazwa.value, skrot=tag, zalozyciel=self.zalozyciel.value)
        thread = await forum.create_thread(name=f"[{tag}] {self.nazwa.value}", embed=embed, view=view)
        await interaction.response.send_message(f"✅ Wniosek wysłany: {thread.thread.mention}", ephemeral=True)


class ModalTransfer(ui.Modal, title="🤝 Wniosek Transferowy (Z Klubu lub Wolny)"):
    zawodnik = ui.TextInput(label="Zawodnik (@Oznaczenie lub Imię)")
    klub_kup = ui.TextInput(label="Kupujący (Skrót)", min_length=3, max_length=3)
    klub_sprzed = ui.TextInput(label="Sprzedający (Wpisz BRAK jeśli nie ma klubu)", min_length=3, max_length=4)
    kwota = ui.TextInput(label="Kwota Transferu (np. 50000, 0 dla wolnych)")
    warunki = ui.TextInput(label="Nowa Klauzula", required=False, placeholder="Opcjonalnie (np. 100000)")

    async def on_submit(self, interaction: discord.Interaction):
        forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
        kup = clean_tag(self.klub_kup.value)
        sprzed_raw = clean_tag(self.klub_sprzed.value)
        bez_klubu = sprzed_raw in ["BRAK", "NONE", "NIE"]
        db = load_db()

        # Zabezpieczenie przed podszywaniem się pod klub
        if not has_club_board_role(interaction.user, kup, db):
            return await interaction.response.send_message(f"❌ Odmowa dostępu: Nie jesteś w Zarządzie `{kup}`, ani w Federacji!", ephemeral=True)

        if kup not in db["kluby"]:
            return await interaction.response.send_message(f"❌ Klub kupujący `{kup}` nie istnieje!", ephemeral=True)
        if not bez_klubu and sprzed_raw not in db["kluby"]:
            return await interaction.response.send_message(f"❌ Klub sprzedający `{sprzed_raw}` nie istnieje!", ephemeral=True)

        czy_klauzula = False
        if not bez_klubu:
            dane_gracza = db["zawodnicy"].get(self.zawodnik.value)
            if dane_gracza and dane_gracza.get("klauzula") and dane_gracza["klauzula"].lower() != "brak":
                try:
                    kwota_int = int("".join(filter(str.isdigit, self.kwota.value)))
                    klauz_int = int("".join(filter(str.isdigit, str(dane_gracza["klauzula"]))))
                    if kwota_int >= klauz_int and klauz_int > 0: czy_klauzula = True
                except: pass

        klauz_val = self.warunki.value.strip() if self.warunki.value else "Brak"
        wymaga_sprzedawcy = not bez_klubu and not czy_klauzula
        
        tytul = "🔥 Wykupienie Klauzuli" if czy_klauzula else ("👤 Rejestracja Gracza" if bez_klubu else "🤝 Transfer Negocjowany")
        kolor = 0xe67e22 if czy_klauzula else (0x3498db if bez_klubu else 0x9b59b6)
        
        embed = discord.Embed(title=f"{tytul}: {self.zawodnik.value}", color=kolor)
        embed.add_field(name="Kupujący", value=f"`{kup}`", inline=True)
        if not bez_klubu: embed.add_field(name="Sprzedający", value=f"`{sprzed_raw}`", inline=True)
        embed.add_field(name="Kwota", value=f"`{self.kwota.value}`", inline=True)
        embed.add_field(name="Nowa Klauzula", value=f"`{klauz_val}`", inline=False)
        
        status_txt = "⏳ Wymagane podpisy:\n"
        status_txt += "• Gracz (Osobiście lub Zastępczo przez Zarząd)\n"
        if wymaga_sprzedawcy: status_txt += f"• Zarząd Klubu Sprzedającego (`{sprzed_raw}`)\n"
        embed.add_field(name="Status", value=status_txt, inline=False)

        view = WidokPodpisu(gracz=self.zawodnik.value, kup=kup, sprzed=sprzed_raw if not bez_klubu else None, kwota=self.kwota.value, klauz=klauz_val, wym_sprzed=wymaga_sprzedawcy)
        thread = await forum.create_thread(name=f"[{kup}] Transfer: {self.zawodnik.value}", embed=embed, view=view)
        await interaction.response.send_message("✅ Wniosek utworzony.", ephemeral=True)


# ==========================================
# WIDOKI I PRZYCISKI
# ==========================================
class WidokZatwierdzeniaKlubu(ui.View):
    def __init__(self, nazwa, skrot, zalozyciel):
        super().__init__(timeout=None)
        self.nazwa = nazwa
        self.skrot = skrot
        self.zalozyciel = zalozyciel

    @ui.button(label="Zatwierdź & Utwórz Role", style=discord.ButtonStyle.green, custom_id="btn_appr_club")
    async def zatwierdz(self, interaction: discord.Interaction, button):
        if not is_federation(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień!", ephemeral=True)
        await interaction.response.defer()

        # Tworzenie ról na serwerze
        guild = interaction.guild
        base_role = guild.get_role(ROLA_WZORZEC_ID)
        if not base_role:
            return await interaction.followup.send("❌ Błąd krytyczny: Nie znaleziono roli wzorcowej na serwerze!", ephemeral=True)

        rola_zarzad = await guild.create_role(name=f"⚽・{self.skrot} - Zarząd", permissions=base_role.permissions, hoist=base_role.hoist, mentionable=base_role.mentionable)
        rola_zawod = await guild.create_role(name=f"⚽・{self.skrot} - Zawodnik", permissions=base_role.permissions, hoist=base_role.hoist, mentionable=base_role.mentionable)

        # Jeśli oznaczono kogoś, nadajemy mu automatycznie rolę Zarządu
        zal_ids = extract_ids(self.zalozyciel)
        if zal_ids:
            member = guild.get_member(zal_ids[0])
            if member: await member.add_roles(rola_zarzad)

        db = load_db()
        db["kluby"][self.skrot] = {
            "nazwa": self.nazwa,
            "rola_zarzad": rola_zarzad.id,
            "rola_zawodnik": rola_zawod.id
        }
        save_db(db)

        embed = interaction.message.embeds[0]
        embed.color = 0x2ecc71
        embed.title = f"✅ Zaakceptowano: {self.nazwa}"
        embed.add_field(name="Automatyka Ról", value="Utworzono i przypisano systemowe role klubu.", inline=False)
        await interaction.message.edit(embed=embed, view=None)

        komunikaty = interaction.guild.get_channel(CHANNEL_KOMUNIKATY_ID)
        if komunikaty: await komunikaty.send(f"📢 **NOWY KLUB!**\n> Drużyna **{self.nazwa}** (`{self.skrot}`) została oficjalnie zarejestrowana!")

class WidokPodpisu(ui.View):
    def __init__(self, gracz, kup, sprzed, kwota, klauz, wym_sprzed=False):
        super().__init__(timeout=None)
        self.gracz = gracz
        self.kup = kup
        self.sprzed = sprzed
        self.kwota = kwota
        self.klauz = klauz
        self.wym_sprzed = wym_sprzed
        self.p_gracz = False
        self.p_sprzed = False if wym_sprzed else True
        self.gracz_dc_id = None

    def odswiez(self, embed):
        t = f"• Zawodnik: {'✅ Podpisano' if self.p_gracz else '⏳ Oczekuje'}\n"
        if self.wym_sprzed: t += f"• Zarząd (`{self.sprzed}`): {'✅ Zgoda' if self.p_sprzed else '⏳ Oczekuje'}\n"
        t += "• Federacja: ⏳ Oczekuje na zatwierdzenie"
        for f in embed.fields:
            if f.name == "Status": f.value = t
        return embed

    @ui.button(label="✍️ Podpis Gracza", style=discord.ButtonStyle.primary, custom_id="b_gracz_os")
    async def b_gracz_os(self, interaction: discord.Interaction, button):
        # Sprawdzamy czy klikający to rzeczywiście zawodnik, albo czy robi to Federacja
        zawodnik_ids = extract_ids(self.gracz)
        if interaction.user.id not in zawodnik_ids and not is_federation(interaction.user):
            return await interaction.response.send_message("❌ Tylko oznaczony zawodnik może złożyć tu podpis osobisty!", ephemeral=True)
            
        self.p_gracz = True
        if interaction.user.id in zawodnik_ids: self.gracz_dc_id = interaction.user.id
        
        for c in self.children: 
            if c.custom_id in ["b_gracz_os", "b_gracz_tel"]: c.disabled = True
        button.label = "Podpis Osobisty Złożony"
        await interaction.message.edit(embed=self.odswiez(interaction.message.embeds[0]), view=self)
        await interaction.response.send_message("Podpisano.")

    @ui.button(label="📞 Zastępcza Zgoda (Zarząd)", style=discord.ButtonStyle.secondary, custom_id="b_gracz_tel")
    async def b_gracz_tel(self, interaction: discord.Interaction, button):
        db = load_db()
        # Tylko Zarząd kupującego (lub Federacja) może ręczyć za gracza
        if not has_club_board_role(interaction.user, self.kup, db):
            return await interaction.response.send_message(f"❌ Tylko Zarząd kupujący (`{self.kup}`) może potwierdzić zgodę zastępczą!", ephemeral=True)

        self.p_gracz = True
        for c in self.children: 
            if c.custom_id in ["b_gracz_os", "b_gracz_tel"]: c.disabled = True
        button.label = f"Potwierdził: {interaction.user.name}"
        await interaction.message.edit(embed=self.odswiez(interaction.message.embeds[0]), view=self)
        await interaction.response.send_message("Oświadczono zgodę zawodnika.")

    @ui.button(label="🤝 Zgoda Sprzedawcy", style=discord.ButtonStyle.secondary, custom_id="b_sprzed")
    async def b_sprzed(self, interaction: discord.Interaction, button):
        if not self.wym_sprzed: return await interaction.response.send_message("Zgoda niewymagana!", ephemeral=True)
        db = load_db()
        
        # Weryfikacja fizycznej roli zarządu klubu sprzedającego
        if not has_club_board_role(interaction.user, self.sprzed, db):
            return await interaction.response.send_message(f"❌ Musisz posiadać rolę Zarządu klubu `{self.sprzed}`!", ephemeral=True)

        self.p_sprzed = True
        button.disabled = True
        button.label = "Wydano Zgodę"
        await interaction.message.edit(embed=self.odswiez(interaction.message.embeds[0]), view=self)
        await interaction.response.send_message("Zgoda na transfer udzielona.")

    @ui.button(label="✅ Zatwierdź (Federacja)", style=discord.ButtonStyle.green, custom_id="b_fed")
    async def b_fed(self, interaction: discord.Interaction, button):
        if not is_federation(interaction.user): return await interaction.response.send_message("❌ Brak uprawnień Federacji!", ephemeral=True)
        if not self.p_gracz or (self.wym_sprzed and not self.p_sprzed):
            return await interaction.response.send_message("⚠️ Wymuś zgody pozostałymi przyciskami (jako Federacja masz Tryb Nadrzędny), zanim to zatwierdzisz!", ephemeral=True)

        await interaction.response.defer()
        db = load_db()
        guild = interaction.guild

        # Automatyczne czyszczenie i nadawanie RÓL ZAWODNIKA
        if self.gracz_dc_id or extract_ids(self.gracz):
            uid = self.gracz_dc_id if self.gracz_dc_id else extract_ids(self.gracz)[0]
            member = guild.get_member(uid)
            if member:
                # 1. Zdejmij rolę starego klubu
                if self.sprzed and self.sprzed in db["kluby"]:
                    stara_rola_id = db["kluby"][self.sprzed].get("rola_zawodnik")
                    if stara_rola_id:
                        stara_rola = guild.get_role(stara_rola_id)
                        if stara_rola: await member.remove_roles(stara_rola)
                
                # 2. Nadaj rolę nowego klubu
                if self.kup in db["kluby"]:
                    nowa_rola_id = db["kluby"][self.kup].get("rola_zawodnik")
                    if nowa_rola_id:
                        nowa_rola = guild.get_role(nowa_rola_id)
                        if nowa_rola: await member.add_roles(nowa_rola)

        db["zawodnicy"][self.gracz] = {"klub": self.kup, "klauzula": self.klauz}
        save_db(db)

        embed = interaction.message.embeds[0]
        embed.color = 0x2ecc71
        embed.title = f"✅ SFINALIZOWANO: {self.gracz}"
        embed.set_footer(text="System automatycznie przepisał role klubowe gracza.")
        await interaction.message.edit(embed=embed, view=None)

        kom = interaction.guild.get_channel(CHANNEL_KOMUNIKATY_ID)
        if kom: await kom.send(f"📢 **OFICJALNY KOMUNIKAT**\n> Zawodnik **{self.gracz}** dołącza do **{db['kluby'][self.kup]['nazwa']}**!\n> Kwota: `{self.kwota}` | Klauzula: `{self.klauz}`")


# ==========================================
# GŁÓWNY PANEL STARTOWY
# ==========================================
class WidokPaneluGlownego(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @ui.button(label="Rejestracja Klubu", style=discord.ButtonStyle.primary, emoji="📝", custom_id="p_klub")
    async def b_k(self, i, b): await i.response.send_modal(ModalRejestracjaKlubu())
    @ui.button(label="Wniosek Transferowy / Podpisanie Gracza", style=discord.ButtonStyle.secondary, emoji="🤝", custom_id="p_trans")
    async def b_t(self, i, b): await i.response.send_modal(ModalTransfer())

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_panel(ctx):
    embed = discord.Embed(title="🏛️ Panel Federacji", color=0x2b2d31)
    embed.description = "Wybierz odpowiedni wniosek:\n\n**📝 Rejestracja Klubu** – Załóż nową drużynę.\n**🤝 Wniosek Transferowy** – Kupno z innego klubu lub rejestracja gracza bez drużyny."
    await ctx.send(embed=embed, view=WidokPaneluGlownego())
    await ctx.message.delete()

bot.run(os.getenv("DISCORD_TOKEN"))