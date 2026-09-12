import os
import tempfile
from datetime import datetime
import discord
from discord.ext import commands
from config import DISCORD_TOKEN, GUILD_ID
import database
from views.main_panel import WidokPaneluGlownego
from views.market_panel import WidokRynkuTransferowego
from views.application_view import ForumApplicationView
from tasks.expirations import setup_expirations_task
from utils.helpers import is_federation

# Inicjalizacja bazy danych SQLite i ewentualna migracja ze starego JSON
database.init_db()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

expirations_task = setup_expirations_task(bot, guild_id=GUILD_ID or None)


# ─── KOMENDA SETUP PANELU ───
@bot.command()
@commands.has_permissions(administrator=True)
async def setup_panel(ctx):
    """
    Wysyła DWA panele:
    1️⃣ Biuro Federacji – oficjalne procesy ligowe (Rejestracja, Podpisanie, Transfer, Wypożyczenie, Aneks, Rozwiązanie, Rebranding)
    2️⃣ Rynek Transferowy – giełda graczy i przegląd składów
    """
    # ─── Wiadomość 1: Biuro Federacji ───
    embed1 = discord.Embed(
        title="🏛️ Biuro Federacji",
        description=(
            "Oficjalne procesy rejestracyjno-transferowe. Bot otworzy prywatny kanał ticketu, "
            "gdzie odpowiesz na pytania i możesz swobodnie oznaczać (@) użytkowników.\n\n"
            "**📝 Rejestracja Klubu** · Zakładanie nowej drużyny w lidze\n"
            "**👤 Podpisanie Gracza** · Rejestracja wolnego agenta (limit: 3 graczy)\n"
            "**🤝 Wniosek Transferowy** · Kupno zawodnika z innego klubu\n"
            "**⏱️ Wypożyczenie** · Czasowe przejście z automatycznym powrotem\n"
            "**📄 Aneks do Umowy** · Przedłużenie wygasającego kontraktu / zmiana klauzuli\n"
            "**❌ Rozwiązanie Umowy** · Za porozumieniem stron lub dyscyplinarne\n"
            "**🔄 Rebranding Klubu** · Oficjalna zmiana nazwy lub 3-literowego TAGu"
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
            "Zarejestruj się jako wolny agent – widoczny dla zarządów szukających zawodników. "
            "Ponowne kliknięcie usunie Cię z listy.\n\n"
            "**🔍 Szukam Zawodnika**\n"
            "Przeglądaj listę graczy bez klubu, szukających nowej drużyny.\n\n"
            "**📋 Składy Drużyn**\n"
            "Przeglądaj pełne kadry drużyn z wizualnymi paskami zapełnienia."
        ),
        color=0x1e1f22
    )
    embed2.set_footer(text="Liga Federacji • Rynek")
    await ctx.send(embed=embed2, view=WidokRynkuTransferowego())

    try:
        await ctx.message.delete()
    except Exception:
        pass


# ─── KOMENDY BEZPIECZEŃSTWA BAZY DANYCH (ADMIN / FEDERACJA) ───
@bot.command()
async def backup_db(ctx):
    """Wykonuje atomowy backup bazy SQLite (VACUUM INTO) i przesyła plik .db."""
    if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
        return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")

    temp_fd, temp_path = tempfile.mkstemp(suffix=".db", prefix="liga_backup_")
    os.close(temp_fd)
    os.remove(temp_path)  # VACUUM INTO sam tworzy plik docelowy

    try:
        database.backup_database_vacuum(temp_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"liga_backup_{timestamp}.db"
        await ctx.reply(
            f"📦 **Kopia zapasowa bazy danych** (`{filename}`):\n"
            f"> Tryb: WAL-safe atomic vacuum snapshot",
            file=discord.File(temp_path, filename=filename)
        )
    except Exception as e:
        await ctx.reply(f"❌ Błąd tworzenia kopii zapasowej: `{e}`")
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@bot.command()
async def db_stats(ctx):
    """Wyświetla statystyki techniczne pliku bazy SQLite."""
    if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
        return await ctx.reply("❌ Brak uprawnień.")

    stats = database.get_db_file_stats()
    embed = discord.Embed(title="🗄️ Statystyki bazy SQLite", color=0x2b2d31)
    embed.add_field(name="Rozmiar pliku", value=f"`{stats.get('file_size_kb', 0)} KB`", inline=True)
    embed.add_field(name="Tryb Journal", value=f"`{stats.get('journal_mode', '?')}`", inline=True)
    embed.add_field(name="Klucze obce", value=f"`{stats.get('foreign_keys', '?')}`", inline=True)

    counts = (
        f"• Kluby: `{stats.get('clubs', 0)}`\n"
        f"• Zawodnicy: `{stats.get('players', 0)}`\n"
        f"• Wolni Agenci: `{stats.get('free_agents', 0)}`\n"
        f"• Wnioski: `{stats.get('applications', 0)}`\n"
        f"• Historia transferów: `{stats.get('transfer_history', 0)}`"
    )
    embed.add_field(name="Liczba rekordów", value=counts, inline=False)
    await ctx.reply(embed=embed)


# ─── BOT START / RESTART (PERSISTENT VIEWS) ───
@bot.event
async def on_ready():
    # Rejestracja trwałych widoków
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
