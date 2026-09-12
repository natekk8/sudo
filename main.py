import discord
from discord.ext import commands
from config import DISCORD_TOKEN, GUILD_ID
import database
from views.main_panel import WidokPaneluGlownego
from views.market_panel import WidokRynkuTransferowego
from views.application_view import ForumApplicationView
from tasks.expirations import setup_expirations_task

# Inicjalizacja bazy danych SQLite i ewentualna migracja ze starego JSON
database.init_db()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

expirations_task = setup_expirations_task(bot, guild_id=GUILD_ID or None)

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_panel(ctx):
    """
    Wysyła DWA panele:
    1️⃣ Biuro Federacji – rejestracje i wnioski (Rejestracja, Podpisanie, Transfer, Wypożyczenie)
    2️⃣ Rynek Transferowy – giełda graczy i przegląd składów
    """
    # ─── Wiadomość 1: Biuro Federacji ───
    embed1 = discord.Embed(
        title="🏛️ Biuro Federacji",
        description=(
            "Oficjalne procesy rejestracyjno-transferowe. Bot otworzy tymczasowy kanał, "
            "gdzie odpiszesz na pytania ankiety możesz swobodnie oznaczać (@) użytkowników.\n\n"
            "**📝 Rejestracja Klubu**\n"
            "Zakładanie nowego zespołu. Potrzebna pełna nazwa, 3-literowy skrót i oznaczenie zarządu.\n\n"
            "**👤 Podpisanie Gracza**\n"
            "Rejestracja wolnego agenta (bez aktywnego kontraktu). Limit: 3 graczy / klub.\n\n"
            "**🤝 Wniosek Transferowy**\n"
            "Kupno gracza z innej drużyny. Wykup klauzulowy nie wymaga zgody sprzedającego.\n\n"
            "**⏱️ Wypożyczenie**\n"
            "Tymczasowe przejście zawodnika. Po terminie gracz automatycznie wraca do macierzystego klubu."
        ),
        color=0x2b2d31
    )
    embed1.set_footer(text="Liga Federacji • Biuro")
    await ctx.send(embed=embed1, view=WidokPaneluGlownego())

    # ─── Wiadomość 2: Rynek Transferowy ───
    embed2 = discord.Embed(
        title="📊 Rynek Transferowy",
        description=(
            "Giełda graczy i baza składów.\n\n"
            "**🙋 Szukam Klubu**\n"
            "Zarejestruj się jako wolny agent – widoczny dla zarządów. "
            "Kliknij ponownie, aby usunąć się z listy.\n\n"
            "**🔍 Szukam Zawodnika**\n"
            "Podgląd listy graczy bez aktywnego kontraktu, szukających nowego klubu.\n\n"
            "**📋 Składy Drużyn**\n"
            "Przeglądaj pełne kadry wszystkich zarejestrowanych drużyn z wizualnym paskiem zapełnienia."
        ),
        color=0x1e1f22
    )
    embed2.set_footer(text="Liga Federacji • Rynek")
    await ctx.send(embed=embed2, view=WidokRynkuTransferowego())

    try:
        await ctx.message.delete()
    except Exception:
        pass

@bot.event
async def on_ready():
    # Rejestracja trwałych widoków (persistence after restart)
    bot.add_view(WidokPaneluGlownego())
    bot.add_view(WidokRynkuTransferowego())

    # Przywrócenie widoków dla wszystkich otwartych wniosków
    pending_apps = database.get_pending_applications()
    restored = 0
    for app in pending_apps:
        msg_id = app.get("message_id")
        if msg_id:
            try:
                bot.add_view(ForumApplicationView(app["id"]), message_id=msg_id)
                restored += 1
            except Exception as e:
                print(f"[on_ready] Błąd przywracania widoku dla wniosku #{app['id']}: {e}")

    print(f"[on_ready] Przywrócono {restored} aktywnych widoków wniosków z bazy SQLite.")

    # Uruchomienie zadania sprawdzającego kontrakty co 30 minut
    if not expirations_task.is_running():
        expirations_task.start()

    print(f"[on_ready] Bot Federacji zalogowany jako: {bot.user} | Guild ID: {GUILD_ID or 'auto'}")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("BŁĄD: Zmienna środowiskowa DISCORD_TOKEN nie została ustawiona!")
    else:
        bot.run(DISCORD_TOKEN)
