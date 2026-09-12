import discord
from discord.ext import commands
from config import DISCORD_TOKEN, GUILD_ID
import database
import utils.league_config as league_config
from views.main_panel import WidokPaneluGlownego
from views.market_panel import WidokRynkuTransferowego
from views.application_view import ForumApplicationView
from tasks.expirations import setup_expirations_task
from utils.helpers import is_federation


# Inicjalizacja bazy danych SQLite
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
    1️⃣ Biuro Federacji – oficjalne procesy ligowe
    2️⃣ Rynek Transferowy – giełda graczy i przegląd składów
    """
    mx = league_config.max_players()
    embed1 = discord.Embed(
        title="🏛️ Biuro Federacji",
        description=(
            "Oficjalne procesy rejestracyjno-transferowe. Bot otworzy prywatny kanał ticketu, "
            "gdzie odpowiesz na pytania i możesz swobodnie oznaczać (@) użytkowników.\n\n"
            "**📝 Rejestracja Klubu** · Zakładanie nowej drużyny w lidze\n"
            f"**👤 Podpisanie Gracza** · Rejestracja wolnego agenta (limit: **{mx}** graczy)\n"
            "**🤝 Wniosek Transferowy** · Kupno zawodnika z innego klubu\n"
            "**⏱️ Wypożyczenie** · Czasowe przejście z automatycznym powrotem\n"
            "**📄 Aneks do Umowy** · Przedłużenie wygasającego kontraktu / zmiana klauzuli\n"
            "**❌ Rozwiązanie Umowy** · Za porozumieniem stron lub dyscyplinarne\n"
            "**⚙️ Zarządzanie Klubem** · Zmiana nazwy, TAGu, właściciela lub zarządu drużyny"
        ),
        color=0x2b2d31
    )
    embed1.set_footer(text="Liga Federacji • Biuro")
    await ctx.send(embed=embed1, view=WidokPaneluGlownego())


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


@bot.event
async def on_ready():
    bot.add_view(WidokPaneluGlownego())
    bot.add_view(WidokRynkuTransferowego())

    for app in database.get_pending_applications():
        msg_id = app.get("message_id")
        if msg_id:
            try:
                bot.add_view(ForumApplicationView(app["id"]), message_id=msg_id)
            except Exception as e:
                print(f"[on_ready] Błąd widoku #{app['id']}: {e}")

    for cog in ['cogs.admin', 'cogs.market', 'cogs.setup_cog']:
        try:
            await bot.load_extension(cog)
        except Exception as e:
            print(f"[on_ready] Błąd ładowania cog {cog}: {e}")

    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            await bot.tree.sync(guild=guild_obj)
        await bot.tree.sync()
    except Exception as e:
        print(f"[on_ready] Błąd synchronizacji slash commands: {e}")

    if not expirations_task.is_running():
        expirations_task.start()

    print(f"[on_ready] Bot Federacji zalogowany jako: {bot.user} | Guild ID: {GUILD_ID or 'auto'}")


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("BŁĄD: Zmienna środowiskowa DISCORD_TOKEN nie została ustawiona!")
    else:
        bot.run(DISCORD_TOKEN)
