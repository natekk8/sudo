import os
import json
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands
from discord import ui

# --- 1. NAPRAWA POŁĄCZEŃ SIECIOWYCH (IPv4) ---
orig_getaddrinfo = socket.getaddrinfo
def patched_getaddrinfo(*args, **kwargs):
    responses = orig_getaddrinfo(*args, **kwargs)
    ipv4_responses = [r for r in responses if r[0] == socket.AF_INET]
    return ipv4_responses if ipv4_responses else responses
socket.getaddrinfo = patched_getaddrinfo

# --- 2. MINI SERWER HTTP (Wymagany do ciągłego działania 24/7) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot Federacji dziala poprawnie 24/7.")
    def log_message(self, format, *args):
        return

def run_http_server():
    port = int(os.getenv("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_http_server, daemon=True).start()

# ==========================================
# KONFIGURACJA ID (Role i Kanały)
# ==========================================
ROLE_FEDERACJA_ID = 1545869517459161092   # Zarząd Federacji
ROLE_ZAWODNIK_ID = 1545869510123200643    # Rola Zawodnika
ROLE_SPOLECZNOSC_ID = 1545869508915241043 # Rola Społeczności

# Wpisz tutaj ID swoich kanałów Discord:
CHANNEL_FORUM_ID = 0          # ID kanału forum: 🏛️・biuro-federacji
CHANNEL_KOMUNIKATY_ID = 0     # ID kanału tekstowego: 📢・oficjalne-komunikaty

DB_FILE = "baza_ligi.json"

def load_db():
    if not os.path.exists(DB_FILE):
        return {"kluby": {}, "zawodnicy": {}}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

def is_federation(member: discord.Member) -> bool:
    return any(r.id == ROLE_FEDERACJA_ID for r in member.roles)

def clean_tag(tag: str) -> str:
    return tag.strip().upper()

# ==========================================
# MODALE (FORMULARZE)
# ==========================================

class ModalRejestracjaKlubu(ui.Modal, title="📝 Rejestracja Nowego Klubu"):
    nazwa = ui.TextInput(label="Pełna nazwa klubu", placeholder="np. FC Victoria", max_length=60)
    skrot = ui.TextInput(label="Skrót (dokładnie 3 litery)", placeholder="np. VIC", min_length=3, max_length=3)
    zalozyciel = ui.TextInput(label="Założyciel", placeholder="@Wzmianka lub Jan Kowalski - Założyciel")
    zarzad = ui.TextInput(
        label="Pozostały Zarząd", 
        style=discord.TextStyle.paragraph, 
        placeholder="Wpisz pozostałych członków (np. @Marek, Adam Nowak [Brak DC])",
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
        if not forum:
            await interaction.response.send_message("❌ Błąd: Nie skonfigurowano ID kanału forum w kodzie bota!", ephemeral=True)
            return

        tag = clean_tag(self.skrot.value)
        db = load_db()

        if tag in db["kluby"]:
            await interaction.response.send_message(f"❌ Klub ze skrótem `{tag}` już istnieje w rejestrze!", ephemeral=True)
            return

        embed = discord.Embed(title=f"🏛️ Wniosek o Rejestrację Klubu: {self.nazwa.value}", color=0x3498db)
        embed.add_field(name="🏷️ Skrót", value=f"`{tag}`", inline=True)
        embed.add_field(name="👑 Założyciel", value=self.zalozyciel.value, inline=True)
        embed.add_field(name="📩 Zgłaszający", value=interaction.user.mention, inline=True)
        embed.add_field(name="👥 Skład Zarządu", value=self.zarzad.value or "Brak innych osób", inline=False)
        embed.set_footer(text="Decyzja należy wyłącznie do Zarządu Federacji.")

        view = WidokZatwierdzeniaKlubu(nazwa_klubu=self.nazwa.value, skrot=tag, autor_id=interaction.user.id)
        thread = await forum.create_thread(name=f"[{tag}] {self.nazwa.value}", embed=embed, view=view)

        await interaction.response.send_message(f"✅ Złożono wniosek! Przejdź do wątku: {thread.thread.mention}", ephemeral=True)


class ModalWolnyAgent(ui.Modal, title="✍️ Kontrakt: Wolny Agent"):
    zawodnik = ui.TextInput(label="Zawodnik", placeholder="@Wzmianka lub Jan Nowak [Brak DC]")
    skrot_klubu = ui.TextInput(label="Skrót Twojego Klubu (3 litery)", min_length=3, max_length=3)
    czas_trwania = ui.TextInput(label="Czas trwania kontraktu", placeholder="np. 1 sezon / do końca roku")
    klauzula = ui.TextInput(label="Klauzula odstępnego (kwota wykupu)", placeholder="np. 50 000 monet / brak")

    async def on_submit(self, interaction: discord.Interaction):
        forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
        tag = clean_tag(self.skrot_klubu.value)
        db = load_db()

        if tag not in db["kluby"]:
            await interaction.response.send_message(f"❌ Klub `{tag}` nie jest zarejestrowany w Federacji!", ephemeral=True)
            return

        embed = discord.Embed(title=f"📄 Kontrakt Wolnego Agenta: {self.zawodnik.value}", color=0x2ecc71)
        embed.add_field(name="Klub", value=f"{db['kluby'][tag]['nazwa']} (`{tag}`)", inline=True)
        embed.add_field(name="Czas trwania", value=self.czas_trwania.value, inline=True)
        embed.add_field(name="Klauzula odstępnego", value=self.klauzula.value, inline=True)
        embed.add_field(name="Status Podpisów", value="⏳ Oczekiwanie na podpis zawodnika lub autoryzację telefoniczną zarządu.", inline=False)

        view = WidokPodpisuTransferu(
            typ="WOLNY_AGENT",
            gracz=self.zawodnik.value,
            klub_kupujacy=tag,
            klub_sprzedajacy=None,
            kwota="0",
            klauzula=self.klauzula.value,
            czas=self.czas_trwania.value
        )
        thread = await forum.create_thread(name=f"[WOLNY AGENT] {self.zawodnik.value} ➡️ {tag}", embed=embed, view=view)
        await interaction.response.send_message(f"✅ Złożono wniosek! Wątek: {thread.thread.mention}", ephemeral=True)


class ModalTransfer(ui.Modal, title="🤝 Transfer / Wykupienie Klauzuli"):
    zawodnik = ui.TextInput(label="Zawodnik", placeholder="@Wzmianka lub Jan Nowak [Brak DC]")
    klub_kup = ui.TextInput(label="Twój Klub (Kupujący - 3 litery)", min_length=3, max_length=3)
    klub_sprzed = ui.TextInput(label="Klub Obecny (Sprzedający - 3 litery)", min_length=3, max_length=3)
    kwota = ui.TextInput(label="Oferowana Kwota Transferu", placeholder="np. 80000")
    nowa_klauzula_czas = ui.TextInput(
        label="Nowa Klauzula i Długość Kontraktu",
        placeholder="Klauzula: 100 000 | Czas: 2 sezony"
    )

    async def on_submit(self, interaction: discord.Interaction):
        forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
        tag_kup = clean_tag(self.klub_kup.value)
        tag_sprzed = clean_tag(self.klub_sprzed.value)
        db = load_db()

        if tag_kup not in db["kluby"] or tag_sprzed not in db["kluby"]:
            await interaction.response.send_message("❌ Jeden z podanych klubów nie istnieje w bazie Federacji!", ephemeral=True)
            return

        dane_gracza = db["zawodnicy"].get(self.zawodnik.value)
        czy_klauzula = False
        if dane_gracza and dane_gracza.get("klauzula"):
            try:
                kwota_int = int("".join(filter(str.isdigit, self.kwota.value)))
                klauzula_int = int("".join(filter(str.isdigit, str(dane_gracza["klauzula"]))))
                if kwota_int >= klauzula_int and klauzula_int > 0:
                    czy_klauzula = True
            except ValueError:
                pass

        typ_transakcji = "KLAUZULA" if czy_klauzula else "TRANSFER"
        kolor = 0xe67e22 if czy_klauzula else 0x9b59b6
        tytul = f"🔥 Aktywacja Klauzuli Wykupu: {self.zawodnik.value}" if czy_klauzula else f"🤝 Negocjacje Transferowe: {self.zawodnik.value}"

        embed = discord.Embed(title=tytul, color=kolor)
        embed.add_field(name="Kupujący", value=f"`{tag_kup}`", inline=True)
        embed.add_field(name="Sprzedający", value=f"`{tag_sprzed}`", inline=True)
        embed.add_field(name="Kwota transakcji", value=self.kwota.value, inline=True)
        embed.add_field(name="Warunki nowego kontraktu", value=self.nowa_klauzula_czas.value, inline=False)
        
        status_info = (
            "⚡ **Klauzula aktywowana!** Zgoda klubu sprzedającego NIE JEST wymagana.\n"
            "⏳ Oczekiwanie na podpis zawodnika i akceptację Federacji."
            if czy_klauzula else
            "⏳ Wymagane podpisy:\n1. Klub Sprzedający\n2. Zawodnik (lub tel.)\n3. Zarząd Federacji."
        )
        embed.add_field(name="Status Podpisów", value=status_info, inline=False)

        view = WidokPodpisuTransferu(
            typ=typ_transakcji,
            gracz=self.zawodnik.value,
            klub_kupujacy=tag_kup,
            klub_sprzedajacy=tag_sprzed,
            kwota=self.kwota.value,
            klauzula=self.nowa_klauzula_czas.value,
            czas="Ustalono w warunkach",
            wymaga_zgody_sprzedawcy=(not czy_klauzula)
        )
        thread = await forum.create_thread(name=f"[{typ_transakcji}] {self.zawodnik.value}: {tag_sprzed} ➡️ {tag_kup}", embed=embed, view=view)
        await interaction.response.send_message(f"✅ Utworzono wniosek: {thread.thread.mention}", ephemeral=True)


class ModalWypozyczenie(ui.Modal, title="⏱️ Wypożyczenie Zawodnika"):
    zawodnik = ui.TextInput(label="Zawodnik", placeholder="@Wzmianka lub Jan Nowak [Brak DC]")
    klub_oddajacy = ui.TextInput(label="Klub Oddający (3 litery)", min_length=3, max_length=3)
    klub_przyjmujacy = ui.TextInput(label="Klub Przyjmujący (3 litery)", min_length=3, max_length=3)
    czas_trwania = ui.TextInput(label="Czas trwania (np. do 10. kolejki)", placeholder="np. Do końca rundy")
    oplata = ui.TextInput(label="Opłata za wypożyczenie (lub 0)", placeholder="0", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        forum = interaction.guild.get_channel(CHANNEL_FORUM_ID)
        tag_odd = clean_tag(self.klub_oddajacy.value)
        tag_przyj = clean_tag(self.klub_przyjmujacy.value)
        db = load_db()

        if tag_odd not in db["kluby"] or tag_przyj not in db["kluby"]:
            await interaction.response.send_message("❌ Podane kluby muszą być zarejestrowane!", ephemeral=True)
            return

        embed = discord.Embed(title=f"⏱️ Wniosek o Wypożyczenie: {self.zawodnik.value}", color=0x1abc9c)
        embed.add_field(name="Klub Oddający", value=f"`{tag_odd}`", inline=True)
        embed.add_field(name="Klub Przyjmujący", value=f"`{tag_przyj}`", inline=True)
        embed.add_field(name="Okres wypożyczenia", value=self.czas_trwania.value, inline=True)
        embed.add_field(name="Opłata", value=self.oplata.value or "Brak opłaty", inline=True)
        embed.add_field(name="Status Podpisów", value="⏳ Oczekiwanie na akceptację obu klubów i zawodnika.", inline=False)

        view = WidokPodpisuTransferu(
            typ="WYPOZYCZENIE",
            gracz=self.zawodnik.value,
            klub_kupujacy=tag_przyj,
            klub_sprzedajacy=tag_odd,
            kwota=self.oplata.value or "0",
            klauzula="Brak (Wypożyczenie)",
            czas=self.czas_trwania.value,
            wymaga_zgody_sprzedawcy=True
        )
        thread = await forum.create_thread(name=f"[WYPOŻYCZENIE] {self.zawodnik.value}: {tag_odd} ➡️ {tag_przyj}", embed=embed, view=view)
        await interaction.response.send_message(f"✅ Wniosek utworzony: {thread.thread.mention}", ephemeral=True)


# ==========================================
# WIDOKI I PRZYCISKI W WĄTKACH
# ==========================================

class WidokZatwierdzeniaKlubu(ui.View):
    def __init__(self, nazwa_klubu: str, skrot: str, autor_id: int):
        super().__init__(timeout=None)
        self.nazwa_klubu = nazwa_klubu
        self.skrot = skrot
        self.autor_id = autor_id

    @ui.button(label="Zatwierdź Klub", style=discord.ButtonStyle.green, emoji="✅", custom_id="btn_appr_club")
    async def zatwierdz(self, interaction: discord.Interaction, button: ui.Button):
        if not is_federation(interaction.user):
            await interaction.response.send_message("❌ Tylko Zarząd Federacji ma do tego uprawnienia!", ephemeral=True)
            return

        db = load_db()
        db["kluby"][self.skrot] = {
            "nazwa": self.nazwa_klubu,
            "autor_id": self.autor_id,
            "kadra": []
        }
        save_db(db)

        embed = interaction.message.embeds[0]
        embed.color = 0x2ecc71
        embed.title = f"✅ Zaakceptowano: {self.nazwa_klubu}"
        await interaction.message.edit(embed=embed, view=None)

        kan_komunikaty = interaction.guild.get_channel(CHANNEL_KOMUNIKATY_ID)
        if kan_komunikaty:
            await kan_komunikaty.send(
                f"📢 **NOWY KLUB W FEDERACJI!**\n"
                f"Klub **{self.nazwa_klubu}** (skrót: `{self.skrot}`) został oficjalnie zatwierdzony!"
            )
        await interaction.response.send_message("Klub zatwierdzony!", ephemeral=True)

    @ui.button(label="Odrzuć Wniosek", style=discord.ButtonStyle.red, emoji="❌", custom_id="btn_reje_club")
    async def odrzuc(self, interaction: discord.Interaction, button: ui.Button):
        if not is_federation(interaction.user):
            await interaction.response.send_message("❌ Brak uprawnień!", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        embed.color = 0xe74c3c
        embed.title = f"❌ Odrzucono: {self.nazwa_klubu}"
        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message("Wniosek odrzucony.", ephemeral=True)


class WidokPodpisuTransferu(ui.View):
    def __init__(self, typ, gracz, klub_kupujacy, klub_sprzedajacy, kwota, klauzula, czas, wymaga_zgody_sprzedawcy=False):
        super().__init__(timeout=None)
        self.typ = typ
        self.gracz = gracz
        self.klub_kupujacy = klub_kupujacy
        self.klub_sprzedajacy = klub_sprzedajacy
        self.kwota = kwota
        self.klauzula = klauzula
        self.czas = czas
        self.wymaga_zgody_sprzedawcy = wymaga_zgody_sprzedawcy

        self.podpis_gracza = False
        self.podpis_sprzedawcy = False if wymaga_zgody_sprzedawcy else True

    def aktualizuj_embed(self, embed: discord.Embed):
        tekst = ""
        tekst += f"• Zawodnik / Zarząd (tel.): {'✅ Podpisano' if self.podpis_gracza else '⏳ Oczekuje'}\n"
        if self.wymaga_zgody_sprzedawcy:
            tekst += f"• Klub Sprzedający (`{self.klub_sprzedajacy}`): {'✅ Zaakceptowano' if self.podpis_sprzedawcy else '⏳ Oczekuje'}\n"
        else:
            tekst += "• Klub Sprzedający: ⚡ *Zgoda niewymagana (Klauzula/Wolny Agent)*\n"
        tekst += "• Decyzja Federacji: ⏳ Oczekuje na komplet podpisów"

        for field in embed.fields:
            if field.name == "Status Podpisów":
                field.value = tekst
        return embed

    @ui.button(label="Podpisz (Mam Discorda)", style=discord.ButtonStyle.primary, emoji="✍️", custom_id="btn_sign_dc")
    async def podpis_dc(self, interaction: discord.Interaction, button: ui.Button):
        self.podpis_gracza = True
        button.disabled = True
        button.label = f"Podpisano: {interaction.user.display_name}"
        embed = self.aktualizuj_embed(interaction.message.embeds[0])
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("Podpisano osobiście!", ephemeral=True)

    @ui.button(label="Podpisz za gracza (Tel.)", style=discord.ButtonStyle.secondary, emoji="📞", custom_id="btn_sign_phone")
    async def podpis_tel(self, interaction: discord.Interaction, button: ui.Button):
        self.podpis_gracza = True
        button.disabled = True
        button.label = f"Potwierdzono tel.: {interaction.user.display_name}"
        embed = self.aktualizuj_embed(interaction.message.embeds[0])
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"Zarząd ({interaction.user.mention}) potwierdził zgodę telefonicznie.", ephemeral=False)

    @ui.button(label="Zgoda Klubu Sprzedającego", style=discord.ButtonStyle.primary, emoji="🤝", custom_id="btn_sign_seller")
    async def zgoda_sprzedawcy(self, interaction: discord.Interaction, button: ui.Button):
        if not self.wymaga_zgody_sprzedawcy:
            await interaction.response.send_message("Zgoda starego klubu nie jest tu wymagana!", ephemeral=True)
            return

        self.podpis_sprzedawcy = True
        button.disabled = True
        button.label = f"Zgoda klubu: {interaction.user.display_name}"
        embed = self.aktualizuj_embed(interaction.message.embeds[0])
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"Klub `{self.klub_sprzedajacy}` zaakceptował transakcję!", ephemeral=True)

    @ui.button(label="Zatwierdź w Federacji", style=discord.ButtonStyle.green, emoji="🏛️", custom_id="btn_fed_appr")
    async def zatwierdz_federacja(self, interaction: discord.Interaction, button: ui.Button):
        if not is_federation(interaction.user):
            await interaction.response.send_message("❌ Tylko Zarząd Federacji może zatwierdzić wniosek!", ephemeral=True)
            return

        if not self.podpis_gracza:
            await interaction.response.send_message("⚠️ Brak podpisu zawodnika (lub autoryzacji telefonicznej)!", ephemeral=True)
            return

        if self.wymaga_zgody_sprzedawcy and not self.podpis_sprzedawcy:
            await interaction.response.send_message("⚠️ Klub sprzedający nie wyraził zgody!", ephemeral=True)
            return

        db = load_db()
        db["zawodnicy"][self.gracz] = {
            "klub": self.klub_kupujacy,
            "klauzula": self.klauzula,
            "czas_trwania": self.czas,
            "typ_umowy": self.typ
        }
        if self.klub_kupujacy in db["kluby"]:
            if self.gracz not in db["kluby"][self.klub_kupujacy]["kadra"]:
                db["kluby"][self.klub_kupujacy]["kadra"].append(self.gracz)
        save_db(db)

        if self.gracz.startswith("<@") and self.gracz.endswith(">"):
            uid = int(self.gracz.strip("<@!>"))
            czlonek = interaction.guild.get_member(uid)
            if czlonek:
                rola_zawodnika = interaction.guild.get_role(ROLE_ZAWODNIK_ID)
                if rola_zawodnika:
                    await czlonek.add_roles(rola_zawodnika)

        embed = interaction.message.embeds[0]
        embed.color = 0x2ecc71
        embed.title = f"✅ ZATWIERDZONO: {self.gracz} ➡️ {self.klub_kupujacy}"
        await interaction.message.edit(embed=embed, view=None)

        kan_komunikaty = interaction.guild.get_channel(CHANNEL_KOMUNIKATY_ID)
        if kan_komunikaty:
            akcja = "został wypożyczony do" if self.typ == "WYPOZYCZENIE" else "oficjalnie dołącza do"
            await kan_komunikaty.send(
                f"📢 **KOMUNIKAT FEDERACJI:**\n"
                f"Zawodnik **{self.gracz}** {akcja} drużyny **{self.klub_kupujacy}**!\n"
                f"Kwota: `{self.kwota}` | Klauzula: `{self.klauzula}`"
            )

        await interaction.response.send_message("Wniosek zarejestrowany pomyślnie!", ephemeral=True)

    @ui.button(label="Odrzuć Wniosek", style=discord.ButtonStyle.red, emoji="🚫", custom_id="btn_fed_rej")
    async def odrzuc_federacja(self, interaction: discord.Interaction, button: ui.Button):
        if not is_federation(interaction.user):
            await interaction.response.send_message("❌ Brak uprawnień!", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        embed.color = 0xe74c3c
        embed.title = f"❌ ODRZUCONO: {self.gracz}"
        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message("Transakcja odrzucona przez Federację.", ephemeral=True)


# ==========================================
# GŁÓWNY PANEL (📌・panel-ligowy)
# ==========================================
class WidokPaneluGlownego(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Rejestracja Klubu", style=discord.ButtonStyle.primary, emoji="📝", custom_id="p_klub")
    async def b_klub(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ModalRejestracjaKlubu())

    @ui.button(label="Wolny Agent", style=discord.ButtonStyle.success, emoji="✍️", custom_id="p_wolny")
    async def b_wolny(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ModalWolnyAgent())

    @ui.button(label="Transfer / Klauzula", style=discord.ButtonStyle.secondary, emoji="🤝", custom_id="p_trans")
    async def b_trans(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ModalTransfer())

    @ui.button(label="Wypożyczenie", style=discord.ButtonStyle.secondary, emoji="⏱️", custom_id="p_wyp")
    async def b_wyp(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ModalWypozyczenie())

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_panel(ctx):
    embed = discord.Embed(
        title="🏛️ Federacyjny Panel Ligowy",
        description=(
            "Wybierz odpowiedni wniosek poniżej, aby przesłać sprawę do Federacji:\n\n"
            "• **📝 Rejestracja Klubu** – Nazwa, skrót (3 litery) oraz zarząd.\n"
            "• **✍️ Wolny Agent** – Podpisanie gracza bez klubu.\n"
            "• **🤝 Transfer / Klauzula** – Wykup klauzuli lub negocjacje z klubem.\n"
            "• **⏱️ Wypożyczenie** – Czasowe przejście gracza.\n\n"
            "*(Dla osób bez konta Discord: Zarząd może podpisać wniosek za gracza po weryfikacji telefonicznej).* "
        ),
        color=0x2b2d31
    )
    await ctx.send(embed=embed, view=WidokPaneluGlownego())
    await ctx.message.delete()

@bot.event
async def on_ready():
    bot.add_view(WidokPaneluGlownego())
    print(f"Bot Federacji zalogowany pomyślnie jako: {bot.user}")

bot.run(os.getenv("DISCORD_TOKEN"))
