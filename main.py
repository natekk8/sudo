import os
import discord
from discord.ext import commands
from config import DISCORD_TOKEN
import database
from views.main_panel import WidokPaneluGlownego
from views.application_view import ForumApplicationView
from tasks.expirations import setup_expirations_task

# Inicjalizacja bazy danych SQLite i ewentualna migracja ze starego JSON
database.init_db()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

expirations_task = setup_expirations_task(bot)

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
        "Pozwala zarejestrować zawodnika, który obecnie nie znajduje się w żadnej bazie klubowej (tzw. wolny transfer). Obowiązuje limit maksymalnie 3 graczy w klubie.\n\n"
        "**🤝 Wniosek Transferowy**\n"
        "Rozpoczyna proces kupna gracza z innej drużyny. Jeśli wpisana kwota jest równa lub wyższa od klauzuli, zgoda sprzedającego nie jest wymagana (wykup klauzulowy). Po sfinalizowaniu transferu bot utworzy automatyczny kanał do ustalenia kontraktu.\n\n"
        "**⏱️ Wypożyczenie**\n"
        "Tymczasowe przejście zawodnika do innej drużyny na ustalony czas. Po zakończeniu wypożyczenia zawodnik automatycznie powraca do macierzystego klubu."
    )
    await ctx.send(embed=embed, view=WidokPaneluGlownego())
    await ctx.message.delete()

@bot.event
async def on_ready():
    # Rejestracja trwałego widoku panelu startowego
    bot.add_view(WidokPaneluGlownego())

    # Przywrócenie trwałych widoków dla wszystkich otwartych wniosków na forum
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

    print(f"Przywrócono {restored} aktywnych widoków wniosków z bazy SQLite.")

    # Uruchomienie cyklicznego sprawdzania kontraktów i wypożyczeń
    if not expirations_task.is_running():
        expirations_task.start()

    print(f"Bot Federacji zalogowany pomyślnie jako: {bot.user}")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("BŁĄD: Zmienna środowiskowa DISCORD_TOKEN nie została ustawiona!")
    else:
        bot.run(DISCORD_TOKEN)
