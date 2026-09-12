import os
import json
import re
import asyncio
from datetime import datetime, timedelta
import discord
from discord.ext import commands, tasks
from discord import ui
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# KONFIGURACJA ID
# ==========================================
ROLE_FEDERACJA_ID = 1545869517459161092   
ROLA_WZORZEC_ID = 1545869511318708244  

CHANNEL_FORUM_ID = 1548260165134852157          
CHANNEL_KOMUNIKATY_ID = 1548260354264539196     

DB_FILE = "baza_ligi.json"

# ==========================================
# BAZA DANYCH I FUNKCJE POMOCNICZE
# ==========================================
def load_db():
    if not os.path.exists(DB_FILE):
        return {"kluby": {}, "zawodnicy": {}, "ticket_counter": 0}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_ticket_id():
    db = load_db()
    count = db.setdefault("ticket_counter", 0) + 1
    db["ticket_counter"] = count
    save_db(db)
    return f"{count:03d}"

def extract_ids(text: str):
    if not text: return []
    return [int(uid) for uid in re.findall(r'<@!?(\d+)>', text)]

def is_federation(member):
    return any(r.id == ROLE_FEDERACJA_ID for r in member.roles)

def has_club_board_role(member, club_tag, db):
    if is_federation(member): return True
    if club_tag not in db["kluby"]: return False
    return any(r.id == db["kluby"][club_tag].get("rola_zarzad") for r in member.roles)

def clean_tag(tag: str):
    return tag.strip().upper()

def parse_expiry_date(user_input: str):
    user_input = user_input.strip()
    match_days = re.match(r'^(\d+)(\s*(dni|d|day|days))?$', user_input, re.IGNORECASE)
    if match_days:
        days = int(match_days.group(1))
        if days <= 0:
            return None
        return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(user_input, fmt)
            dt = dt.replace(hour=23, minute=59, second=59)
            if dt < datetime.now():
                return None
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None

async def ping_reprezentantow(thread, kup, sprzed=None):
    db = load_db()
    ids = []
    if kup in db["kluby"]: ids.append(db["kluby"][kup].get("reprezentant_dc"))
    if sprzed and sprzed in db["kluby"]: ids.append(db["kluby"][sprzed].get("reprezentant_dc"))
    ids = [uid for uid in set(ids) if uid]

    if ids:
        mentions = " ".join([f"<@{uid}>" for uid in ids])
        await thread.send(f"🔔 **Wymagana uwaga:** {mentions}\n> Użyjcie przycisków powyżej, aby wydać oświadczenie.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
# SYSTEM TICKETÓW (KANAŁY TYMCZASOWE)
# ==========================================
class WniosekConfirmView(ui.View):
    def __init__(self):
        super().__init__(timeout=900.0)
        self.value = None

    @ui.button(label="Zatwierdź i Wyślij", style=discord.ButtonStyle.green)
    async def btn_confirm(self, interaction: discord.Interaction, button):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @ui.button(label="Anuluj Wniosek", style=discord.ButtonStyle.red)
    async def btn_cancel(self, interaction: discord.Interaction, button):
        self.value = False
        await interaction.response.defer()
        self.stop()

async def utworz_kanal_ticket(interaction: discord.Interaction, prefix: str):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    
    rola_fed = guild.get_role(ROLE_FEDERACJA_ID)
    if rola_fed:
        overwrites[rola_fed] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    nazwa_kanalu = f"{prefix}-{get_ticket_id()}"
    kanal = await guild.create_text_channel(nazwa_kanalu, overwrites=overwrites)
    await interaction.followup.send(f"Utworzono kanał wniosku: {kanal.mention}", ephemeral=True)
    return kanal

async def zadaj_pytanie(kanal, uzytkownik, pytanie):
    await kanal.send(f"🤖 **[Pytanie]** {pytanie}")
    def check(m):
        return m.author == uzytkownik and m.channel == kanal
    try:
        msg = await bot.wait_for('message', check=check, timeout=900.0)
        return msg.content
    except asyncio.TimeoutError:
        await kanal.send("⏳ **Minęło 15 minut braku aktywności.** Wniosek został anulowany, usuwam kanał...")
        await asyncio.sleep(3)
        await kanal.delete()
        raise Exception("Timeout")

# ==========================================
# WIDOKI I PRZYCISKI DO WĄTKÓW (Z FORUM)
# ==========================================
class WidokZatwierdzeniaKlubu(ui.View):
    def __init__(self, nazwa, skrot, zalozyciel_txt, zarzad_txt, rep_id):
        super().__init__(timeout=None)
        self.nazwa = nazwa
        self.skrot = skrot
        self.zalozyciel_txt = zalozyciel_txt
        self.zarzad_txt = zarzad_txt
        self.rep_id = rep_id

    @ui.button(label="Zatwierdź & Utwórz Role", style=discord.ButtonStyle.green, custom_id="btn_appr_club")
    async def zatwierdz(self, interaction: discord.Interaction, button):
        if not is_federation(interaction.user): 
            return await interaction.response.send_message("❌ Brak uprawnień!", ephemeral=True)
        await interaction.response.defer()

        guild = interaction.guild
        base_role = guild.get_role(ROLA_WZORZEC_ID)
        r_zarzad = await guild.create_role(name=f"⚽・{self.skrot} - Zarząd", permissions=base_role.permissions, hoist=base_role.hoist)
        r_zawod = await guild.create_role(name=f"⚽・{self.skrot} - Zawodnik", permissions=base_role.permissions, hoist=base_role.hoist)

        # Wyciągamy wszystkie ID oznaczone w założycielu, zarządzie oraz dodajemy zgłaszającego
        osoby_do_roli = set(extract_ids(self.zalozyciel_txt) + extract_ids(self.zarzad_txt))
        osoby_do_roli.add(self.rep_id)

        for uid in osoby_do_roli:
            member = guild.get_member(uid)
            if member:
                await member.add_roles(r_zarzad)

        db = load_db()
        db["kluby"][self.skrot] = {
            "nazwa": self.nazwa,
            "rola_zarzad": r_zarzad.id,
            "rola_zawodnik": r_zawod.id,
            "reprezentant_dc": self.rep_id
        }
        save_db(db)

        embed = interaction.message.embeds[0]
        embed.color = 0x2ecc71
        embed.title = f"✅ Zaakceptowano: {self.nazwa}"
        embed.add_field(name="Role Zarządu", value="Automatycznie nadano role oznaczonym osobom.", inline=False)
        await interaction.message.edit(embed=embed, view=None)

        kom = interaction.guild.get_channel(CHANNEL_KOMUNIKATY_ID)
        if kom: 
            await kom.send(f"📢 **NOWY KLUB!** Zespół **{self.nazwa}** (`{self.skrot}`) został zarejestrowany!")

class WidokPodpisu(ui.View):
    def __init__(self, gracz, kup, sprzed, kwota, klauz, wym_sprzed, typ, wazny_do):
        super().__init__(timeout=None)
        self.gracz = gracz
        self.kup = kup
        self.sprzed = sprzed
        self.kwota = kwota
        self.klauz = klauz
        self.wym_sprzed = wym_sprzed
        self.typ = typ
        self.wazny_do = wazny_do
        self.p_gracz = False
        self.p_sprzed = not wym_sprzed
        self.gracz_dc_id = None

    def odswiez(self, embed):
        t = f"• Zawodnik: {'✅ Podpisano' if self.p_gracz else '⏳ Oczekuje'}\n"
        if self.wym_sprzed: t += f"• Sprzedający (`{self.sprzed}`): {'✅ Zgoda' if self.p_sprzed else '⏳ Oczekuje'}\n"
        t += "• Federacja: ⏳ Oczekuje"
        for f in embed.fields:
            if f.name == "Status": f.value = t
        return embed

    @ui.button(label="✍️ Podpis Gracza", style=discord.ButtonStyle.primary, custom_id="b_gracz_os")
    async def b_gracz_os(self, interaction: discord.Interaction, button):
        self.p_gracz = True
        self.gracz_dc_id = interaction.user.id 
        for c in self.children: 
            if c.custom_id in ["b_gracz_os", "b_gracz_tel"]: c.disabled = True
        button.label = "Osobiście"
        await interaction.message.edit(embed=self.odswiez(interaction.message.embeds[0]), view=self)
        await interaction.response.send_message("Złożono podpis osobisty.")

    @ui.button(label="📞 Podpis Zastępczy (Zarząd)", style=discord.ButtonStyle.secondary, custom_id="b_gracz_tel")
    async def b_gracz_tel(self, interaction: discord.Interaction, button):
        if not has_club_board_role(interaction.user, self.kup, load_db()):
            return await interaction.response.send_message("❌ Tylko Zarząd kupujący może ręczyć za gracza!", ephemeral=True)
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
        if not is_federation(interaction.user): 
            return await interaction.response.send_message("❌ Brak uprawnień!", ephemeral=True)
        
        await interaction.response.defer()
        db = load_db()
        guild = interaction.guild

        # Ustalenie ID konta gracza: z kliknięcia osobistego lub z oznaczenia w tekście
        final_player_id = self.gracz_dc_id
        if not final_player_id:
            extracted = extract_ids(self.gracz)
            if extracted:
                final_player_id = extracted[0]

        # Automatyczna zmiana ról tylko jeśli gracz posiada/miał oznaczone konto na Discordzie
        if final_player_id:
            member = guild.get_member(final_player_id)
            if member:
                if self.sprzed and self.sprzed in db["kluby"]:
                    old_role = guild.get_role(db["kluby"][self.sprzed].get("rola_zawodnik", 0))
                    if old_role: 
                        await member.remove_roles(old_role)
                if self.kup in db["kluby"]:
                    new_role = guild.get_role(db["kluby"][self.kup].get("rola_zawodnik", 0))
                    if new_role: 
                        await member.add_roles(new_role)

        db["zawodnicy"][self.gracz] = {
            "klub": self.kup,
            "klub_macierzysty": self.sprzed if self.typ == "WYPOZYCZENIE" else self.kup,
            "klauzula": self.klauz,
            "typ": self.typ,
            "wazny_do": self.wazny_do,
            "gracz_dc_id": final_player_id
        }
        save_db(db)

        embed = interaction.message.embeds[0]
        embed.color = 0x2ecc71
        embed.title = f"✅ SFINALIZOWANO: {self.gracz}"
        await interaction.message.edit(embed=embed, view=None)

        kom = interaction.guild.get_channel(CHANNEL_KOMUNIKATY_ID)
        akcja = "został wypożyczony do" if self.typ == "WYPOZYCZENIE" else "dołącza do"
        if kom: 
            await kom.send(f"📢 **OFICJALNIE:** Zawodnik {self.gracz} {akcja} **{db['kluby'][self.kup]['nazwa']}**!\n> Ważność umowy: `{self.wazny_do}` | Klauzula: `{self.klauz}`")

# ==========================================
# PROCESY TICKETÓW (Wywiady z botem)
# ==========================================
async def proces_rejestracji_klubu(interaction):
    kanal = await utworz_kanal_ticket(interaction, "rejestracja")
    try:
        await kanal.send(f"Witaj {interaction.user.mention}! Rozpoczynamy rejestrację klubu.\n*Masz 15 minut na każdą odpowiedź.*")
        nazwa = await zadaj_pytanie(kanal, interaction.user, "Podaj pełną nazwę drużyny (np. FC Łazy):")
        
        while True:
            skrot = await zadaj_pytanie(kanal, interaction.user, "Podaj skrót drużyny (Dokładnie 3 litery, np. LAZ):")
            skrot = clean_tag(skrot)
            db = load_db()
            if len(skrot) != 3:
                await kanal.send("❌ Skrót musi mieć dokładnie 3 litery!")
            elif skrot in db["kluby"]:
                await kanal.send(f"❌ Skrót `{skrot}` jest już zajęty!")
            else:
                break

        zalozyciel = await zadaj_pytanie(kanal, interaction.user, "Oznacz @Głównego Założyciela (lub wpisz Imię jeśli nie ma DC):")
        zarzad = await zadaj_pytanie(kanal, interaction.user, "Oznacz @Pozostały Zarząd (lub wpisz 'Brak'):")

        embed = discord.Embed(title=f"🏛️ Podsumowanie: {nazwa}", color=0x2b2d31)
        embed.add_field(name="Skrót", value=skrot, inline=True)
        embed.add_field(name="Założyciel", value=zalozyciel, inline=True)
        embed.add_field(name="Zarząd", value=zarzad, inline=False)
        
        view = WniosekConfirmView()
        await kanal.send(embed=embed, view=view)
        await view.wait()
        
        if view.value is None:
            await kanal.send("⏳ **Minęło 15 minut bez potwierdzenia.** Zamykam kanał...")
            await asyncio.sleep(3)
            await kanal.delete()
            return
        
        if view.value:
            forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
            v_forum = WidokZatwierdzeniaKlubu(nazwa, skrot, zalozyciel, zarzad, interaction.user.id)
            thread = await forum.create_thread(name=f"[{skrot}] {nazwa}", embed=embed, view=v_forum)
            await kanal.send(f"✅ Wysłano! {thread.thread.mention}. Zamykam kanał...")
        
        await asyncio.sleep(2)
        await kanal.delete()
    except Exception:
        pass

async def proces_podpisania(interaction):
    kanal = await utworz_kanal_ticket(interaction, "kontrakt")
    try:
        db = load_db()
        await kanal.send(f"*Masz 15 minut na każdą odpowiedź.*")
        while True:
            kup = await zadaj_pytanie(kanal, interaction.user, "Podaj skrót TWOJEGO KLUBU (kupującego):")
            kup = clean_tag(kup)
            if not has_club_board_role(interaction.user, kup, db):
                await kanal.send("❌ Nie jesteś w zarządzie tego klubu!")
            else: break
            
        gracz = await zadaj_pytanie(kanal, interaction.user, "Oznacz @Zawodnika (lub wpisz jego imię jeśli nie ma DC):")
        
        while True:
            czas_input = await zadaj_pytanie(kanal, interaction.user, "Podaj długość kontraktu (np. '30' lub '30 dni', albo datę '30.06.2027'):")
            wazny_do = parse_expiry_date(czas_input)
            if wazny_do: break
            await kanal.send("❌ Nieprawidłowy format! Wpisz liczbę dni (np. 14) lub przyszłą datę DD.MM.RRRR.")

        klauz = await zadaj_pytanie(kanal, interaction.user, "Podaj kwotę Klauzuli (lub wpisz 'Brak'):")

        embed = discord.Embed(title=f"📄 Podpisanie Gracza: {gracz}", color=0x3498db)
        embed.add_field(name="Kupujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Wygasa", value=f"`{wazny_do}`", inline=True)
        embed.add_field(name="Klauzula", value=klauz, inline=True)
        embed.add_field(name="Status", value="⏳ Oczekuje na podpisy.", inline=False)

        view = WniosekConfirmView()
        await kanal.send(embed=embed, view=view)
        await view.wait()
        
        if view.value is None:
            await kanal.send("⏳ **Minęło 15 minut bez potwierdzenia.** Zamykam kanał...")
            await asyncio.sleep(3)
            await kanal.delete()
            return
        
        if view.value:
            forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
            v_forum = WidokPodpisu(gracz, kup, None, "0", klauz, False, "BEZ_KLUBU", wazny_do)
            thread = await forum.create_thread(name=f"[{kup}] Nowy Gracz: {gracz}", embed=embed, view=v_forum)
            await ping_reprezentantow(thread.thread, kup)
        
        await kanal.delete()
    except Exception: pass

async def proces_transferu(interaction):
    kanal = await utworz_kanal_ticket(interaction, "transfer")
    try:
        db = load_db()
        await kanal.send(f"*Masz 15 minut na każdą odpowiedź.*")
        while True:
            kup = clean_tag(await zadaj_pytanie(kanal, interaction.user, "Skrót TWOJEGO KLUBU (Kupujący):"))
            if not has_club_board_role(interaction.user, kup, db): await kanal.send("❌ Odmowa dostępu!")
            else: break
            
        while True:
            sprzed = clean_tag(await zadaj_pytanie(kanal, interaction.user, "Skrót KLUBU SPRZEDAJĄCEGO:"))
            if sprzed not in db["kluby"]: await kanal.send("❌ Ten klub nie istnieje w bazie!")
            else: break

        gracz = await zadaj_pytanie(kanal, interaction.user, "Oznacz @Zawodnika (lub wpisz Imię jeśli nie ma DC):")
        kwota = await zadaj_pytanie(kanal, interaction.user, "Kwota transferu:")
        
        while True:
            czas_input = await zadaj_pytanie(kanal, interaction.user, "Długość nowego kontraktu (np. '60 dni' lub '31.12.2026'):")
            wazny_do = parse_expiry_date(czas_input)
            if wazny_do: break
            await kanal.send("❌ Błędny termin! Podaj liczbę dni lub datę DD.MM.RRRR.")

        klauz = await zadaj_pytanie(kanal, interaction.user, "Nowa Klauzula (lub wpisz 'Brak'):")

        czy_klauzula = False
        dane_gracza = db["zawodnicy"].get(gracz)
        if dane_gracza and dane_gracza.get("klauzula") and dane_gracza["klauzula"].lower() != "brak":
            try:
                if int("".join(filter(str.isdigit, kwota))) >= int("".join(filter(str.isdigit, str(dane_gracza["klauzula"])))): czy_klauzula = True
            except: pass

        wym_sprzed = not czy_klauzula
        embed = discord.Embed(title=f"{'🔥 Wykup' if czy_klauzula else '🤝 Transfer'}: {gracz}", color=0xe67e22 if czy_klauzula else 0x9b59b6)
        embed.add_field(name="Kupujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Sprzedający", value=f"`{sprzed}`", inline=True)
        embed.add_field(name="Kwota", value=kwota, inline=True)
        embed.add_field(name="Nowa Klauzula", value=klauz, inline=True)
        embed.add_field(name="Wygasa", value=f"`{wazny_do}`", inline=False)
        embed.add_field(name="Status", value="⚡ Zgoda niewymagana." if czy_klauzula else "⏳ Oczekuje na zgody.", inline=False)

        view = WniosekConfirmView()
        await kanal.send(embed=embed, view=view)
        await view.wait()
        
        if view.value is None:
            await kanal.send("⏳ **Minęło 15 minut bez potwierdzenia.** Zamykam kanał...")
            await asyncio.sleep(3)
            await kanal.delete()
            return
        
        if view.value:
            forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
            v_forum = WidokPodpisu(gracz, kup, sprzed, kwota, klauz, wym_sprzed, "TRANSFER", wazny_do)
            thread = await forum.create_thread(name=f"[{kup}] Transfer: {gracz}", embed=embed, view=v_forum)
            await ping_reprezentantow(thread.thread, kup, sprzed)
        
        await kanal.delete()
    except Exception: pass

async def proces_wypozyczenia(interaction):
    kanal = await utworz_kanal_ticket(interaction, "wypozyczenie")
    try:
        db = load_db()
        await kanal.send(f"*Masz 15 minut na każdą odpowiedź.*")
        while True:
            kup = clean_tag(await zadaj_pytanie(kanal, interaction.user, "Skrót KLUBU PRZYJMUJĄCEGO (Twój):"))
            if not has_club_board_role(interaction.user, kup, db): await kanal.send("❌ Odmowa dostępu!")
            else: break
            
        while True:
            sprzed = clean_tag(await zadaj_pytanie(kanal, interaction.user, "Skrót KLUBU ODDAJĄCEGO:"))
            if sprzed not in db["kluby"]: await kanal.send("❌ Ten klub nie istnieje w bazie!")
            else: break

        gracz = await zadaj_pytanie(kanal, interaction.user, "Oznacz @Zawodnika (lub wpisz Imię jeśli nie ma DC):")
        
        while True:
            czas_input = await zadaj_pytanie(kanal, interaction.user, "Okres wypożyczenia (np. '30 dni' lub '15.01.2027'):")
            wazny_do = parse_expiry_date(czas_input)
            if wazny_do: break
            await kanal.send("❌ Błędny termin! Podaj liczbę dni lub datę DD.MM.RRRR.")

        kwota = await zadaj_pytanie(kanal, interaction.user, "Opłata za wypożyczenie (lub 'Brak'):")

        embed = discord.Embed(title=f"⏱️ Wypożyczenie: {gracz}", color=0x1abc9c)
        embed.add_field(name="Przyjmujący", value=f"`{kup}`", inline=True)
        embed.add_field(name="Oddający", value=f"`{sprzed}`", inline=True)
        embed.add_field(name="Opłata", value=kwota, inline=True)
        embed.add_field(name="Koniec wypożyczenia", value=f"`{wazny_do}`", inline=False)
        embed.add_field(name="Status", value="⏳ Oczekuje na zgody.", inline=False)

        view = WniosekConfirmView()
        await kanal.send(embed=embed, view=view)
        await view.wait()
        
        if view.value is None:
            await kanal.send("⏳ **Minęło 15 minut bez potwierdzenia.** Zamykam kanał...")
            await asyncio.sleep(3)
            await kanal.delete()
            return
        
        if view.value:
            forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
            v_forum = WidokPodpisu(gracz, kup, sprzed, kwota, "Bez zmian", True, "WYPOZYCZENIE", wazny_do)
            thread = await forum.create_thread(name=f"[{kup}] Wypożyczenie: {gracz}", embed=embed, view=v_forum)
            await ping_reprezentantow(thread.thread, kup, sprzed)
        
        await kanal.delete()
    except Exception: pass

# ==========================================
# PĘTLA W TLE (AUTOMATYCZNE WYGASANIE UMÓW)
# ==========================================
@tasks.loop(minutes=60)
async def check_expirations():
    await bot.wait_until_ready()
    db = load_db()
    guild = bot.guilds[0] if bot.guilds else None
    if not guild: return

    kom_channel = guild.get_channel(CHANNEL_KOMUNIKATY_ID)
    now = datetime.now()
    zawodnicy = list(db.get("zawodnicy", {}).items())

    for gracz_nazwa, dane in zawodnicy:
        wazny_do_str = dane.get("wazny_do")
        if not wazny_do_str: continue

        try:
            wazny_do = datetime.strptime(wazny_do_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

        if now >= wazny_do:
            typ = dane.get("typ")
            klub_obecny = dane.get("klub")
            klub_macierzysty = dane.get("klub_macierzysty")
            dc_id = dane.get("gracz_dc_id")
            member = guild.get_member(dc_id) if dc_id else None

            if typ == "WYPOZYCZENIE":
                if member:
                    if klub_obecny in db["kluby"]:
                        r_temp = guild.get_role(db["kluby"][klub_obecny].get("rola_zawodnik", 0))
                        if r_temp: await member.remove_roles(r_temp)
                    if klub_macierzysty in db["kluby"]:
                        r_mac = guild.get_role(db["kluby"][klub_macierzysty].get("rola_zawodnik", 0))
                        if r_mac: await member.add_roles(r_mac)

                db["zawodnicy"][gracz_nazwa]["klub"] = klub_macierzysty
                db["zawodnicy"][gracz_nazwa]["typ"] = "TRANSFER"
                db["zawodnicy"][gracz_nazwa]["wazny_do"] = None
                save_db(db)

                if kom_channel:
                    nazwa_obecny = db["kluby"].get(klub_obecny, {}).get("nazwa", klub_obecny)
                    nazwa_macierz = db["kluby"].get(klub_macierzysty, {}).get("nazwa", klub_macierzysty)
                    await kom_channel.send(
                        f"⏱️ **KONIEC WYPOŻYCZENIA!**\n"
                        f"> Zawodnik **{gracz_nazwa}** zakończył okres wypożyczenia w **{nazwa_obecny}** i wraca do macierzystego klubu **{nazwa_macierz}** (`{klub_macierzysty}`)!"
                    )

            else:
                if member and klub_obecny in db["kluby"]:
                    r_zaw = guild.get_role(db["kluby"][klub_obecny].get("rola_zawodnik", 0))
                    if r_zaw: await member.remove_roles(r_zaw)

                del db["zawodnicy"][gracz_nazwa]
                save_db(db)

                if kom_channel:
                    nazwa_klub = db["kluby"].get(klub_obecny, {}).get("nazwa", klub_obecny)
                    await kom_channel.send(
                        f"📢 **WYGAŚNIĘCIE KONTRAKTU!**\n"
                        f"> Kontrakt zawodnika **{gracz_nazwa}** z drużyną **{nazwa_klub}** (`{klub_obecny}`) dobiegł końca.\n"
                        f"> Zawodnik staje się graczem bez klubu!"
                    )

# ==========================================
# GŁÓWNY PANEL STARTOWY
# ==========================================
class WidokPaneluGlownego(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @ui.button(label="Rejestracja Klubu", style=discord.ButtonStyle.primary, emoji="📝", custom_id="p_klub")
    async def b_k(self, i, b): bot.loop.create_task(proces_rejestracji_klubu(i))
    @ui.button(label="Podpisanie gracza", style=discord.ButtonStyle.success, emoji="👤", custom_id="p_wolny")
    async def b_w(self, i, b): bot.loop.create_task(proces_podpisania(i))
    @ui.button(label="Wniosek Transferowy", style=discord.ButtonStyle.secondary, emoji="🤝", custom_id="p_trans")
    async def b_t(self, i, b): bot.loop.create_task(proces_transferu(i))
    @ui.button(label="Wypożyczenie", style=discord.ButtonStyle.secondary, emoji="⏱️", custom_id="p_wyp")
    async def b_wyp(self, i, b): bot.loop.create_task(proces_wypozyczenia(i))

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_panel(ctx):
    embed = discord.Embed(title="🏛️ Panel Sterowania Federacji", color=0x2b2d31)
    embed.description = (
        "Wybierz akcję z przycisków poniżej. Bot utworzy tymczasowy kanał tekstowy, w którym odpowiesz na pytania ankiety, mogąc swobodnie oznaczać (@) użytkowników.\n\n"
        "**Co robią poszczególne przyciski?**\n"
        "**📝 Rejestracja Klubu**\n"
        "Otwiera proces zakładania nowego zespołu. Wymaga podania pełnej nazwy, trzyliterowego skrótu oraz oznaczenia członków zarządu.\n\n"
        "**👤 Podpisanie gracza (bez klubu)**\n"
        "Pozwala zarejestrować zawodnika, który obecnie nie znajduje się w żadnej bazie klubowej (tzw. wolny transfer). Możesz opcjonalnie zdefiniować mu klauzulę odejścia.\n\n"
        "**🤝 Wniosek Transferowy**\n"
        "Rozpoczyna proces kupna gracza z innej drużyny. Jeśli wpisana kwota jest mniejsza niż klauzula zawodnika, bot zażąda zgody drugiego klubu. Jeśli kwota przekracza klauzulę, transfer traktowany jest jako przymusowy wykup.\n\n"
        "**⏱️ Wypożyczenie**\n"
        "Tymczasowe, płatne lub darmowe przejście zawodnika do innej drużyny na ustalony czas bez ingerencji w jego zapisy klauzulowe."
    )
    await ctx.send(embed=embed, view=WidokPaneluGlownego())
    await ctx.message.delete()

@bot.event
async def on_ready():
    bot.add_view(WidokPaneluGlownego())
    if not check_expirations.is_running():
        check_expirations.start()
    print(f"Bot Federacji zalogowany jako: {bot.user}")

bot.run(os.getenv("DISCORD_TOKEN"))
