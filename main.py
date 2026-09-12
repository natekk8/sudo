import os
import tempfile
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from config import DISCORD_TOKEN, GUILD_ID, CHANNEL_KOMUNIKATY_ID
import database
from views.main_panel import WidokPaneluGlownego
from views.market_panel import WidokRynkuTransferowego
from views.application_view import ForumApplicationView
from tasks.expirations import setup_expirations_task
from utils.helpers import is_federation, parse_schedule_datetime, format_expiry_discord

# Inicjalizacja bazy danych SQLite i ewentualna migracja ze starego JSON
database.init_db()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

expirations_task = setup_expirations_task(bot, guild_id=GUILD_ID or None)


def build_market_status_embed() -> discord.Embed:
    state = database.get_market_state()
    status = state.get("status", "OPEN").upper()
    is_open = status != "CLOSED"
    open_at = state.get("open_at")
    close_at = state.get("close_at")

    color = 0x2ecc71 if is_open else 0xe74c3c
    title = "🟢 Rynek Transferowy jest OTWARTY" if is_open else "🔴 Rynek Transferowy jest ZAMKNIĘTY"

    desc = (
        "Kluby mogą składać wnioski o podpisanie wolnych agentów, transfery oraz wypożyczenia."
        if is_open else
        "Wnioski o podpisanie wolnych agentów, transfery oraz wypożyczenia są obecnie **zablokowane**."
    )

    embed = discord.Embed(title=title, description=desc, color=color)

    if close_at:
        embed.add_field(name="⏰ Zaplanowane zamknięcie", value=format_expiry_discord(close_at), inline=False)
    if open_at:
        embed.add_field(name="🔓 Zaplanowane otwarcie", value=format_expiry_discord(open_at), inline=False)

    embed.set_footer(text="Liga Federacji • Okienko Transferowe")
    return embed


async def announce_market_change(guild: discord.Guild, message: str):
    if not guild: return
    channel = guild.get_channel(CHANNEL_KOMUNIKATY_ID)
    if channel:
        try:
            await channel.send(message, allowed_mentions=discord.AllowedMentions.none())
        except Exception as e:
            print(f"[announce_market_change] Błąd wysyłania komunikatu: {e}")


# ─── KOMENDA SETUP PANELU ───
@bot.command()
@commands.has_permissions(administrator=True)
async def setup_panel(ctx):
    """
    Wysyła DWA panele:
    1️⃣ Biuro Federacji – oficjalne procesy ligowe (Rejestracja, Podpisanie, Transfer, Wypożyczenie, Aneks, Rozwiązanie, Zarządzanie)
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
            "**⚙️ Zarządzanie Klubem** · Zmiana nazwy, TAGu, właściciela lub zarządu drużyny"
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


# ─── KOMENDA RESETU SEZONU (ADMINISTRATOR) ───
@bot.command()
@commands.has_permissions(administrator=True)
async def reset_sezon(ctx):
    """Czyści bazę danych i liczniki, przygotowując ligę na nowy sezon 2026/27."""
    database.reset_database_for_new_season()
    embed = discord.Embed(
        title="🏆 Nowy Sezon 2026/27 Rozpoczęty!",
        description=(
            "Baza danych została zresetowana i zainicjowana na nowy sezon 2026/27:\n"
            "• Tabele `players`, `clubs`, `applications`, `transfer_history`, `free_agents` zostały wyczyszczone.\n"
            "• Licznik ticketów zresetowany do 0.\n"
            "• Okienko transferowe ustawione w stan: **OTWARTY**.\n\n"
            "Zarządy mogą rejestrować nowe kluby i zgłaszać zawodników."
        ),
        color=0x2ecc71
    )
    embed.set_footer(text="Liga Federacji • Sezon 2026/27")
    await ctx.reply(embed=embed)


# ─── SLASH COMMANDS: /RYNEK (ADMIN / FEDERACJA) ───
rynek_slash_group = app_commands.Group(name="rynek", description="Zarządzanie rynkiem transferowym ligi")

@rynek_slash_group.command(name="status", description="Sprawdź stan i harmonogram rynku transferowego")
async def slash_rynek_status(interaction: discord.Interaction):
    embed = build_market_status_embed()
    await interaction.response.send_message(embed=embed)

@rynek_slash_group.command(name="otworz", description="Otwórz rynek transferowy (odblokowuje transfery, kontrakty i wypożyczenia)")
async def slash_rynek_otworz(interaction: discord.Interaction):
    if not (interaction.user.guild_permissions.administrator or is_federation(interaction.user)):
        return await interaction.response.send_message("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.", ephemeral=True)
    database.set_market_status("OPEN", scheduled_open="")
    await announce_market_change(
        interaction.guild,
        "🔓 **RYNEK TRANSFEROWY ZOSTAŁ OTWARTY!**\n"
        "> Zarząd Federacji otworzył okienko transferowe!\n"
        "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało odblokowane."
    )
    await interaction.response.send_message("✅ Rynek transferowy został otwarty!", ephemeral=True)

@rynek_slash_group.command(name="zamknij", description="Zamknij rynek transferowy (blokuje transfery, kontrakty i wypożyczenia)")
async def slash_rynek_zamknij(interaction: discord.Interaction):
    if not (interaction.user.guild_permissions.administrator or is_federation(interaction.user)):
        return await interaction.response.send_message("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.", ephemeral=True)
    database.set_market_status("CLOSED", scheduled_close="")
    await announce_market_change(
        interaction.guild,
        "🔒 **RYNEK TRANSFEROWY ZOSTAŁ ZAMKNIĘTY!**\n"
        "> Zarząd Federacji zamknął okienko transferowe.\n"
        "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało zablokowane."
    )
    await interaction.response.send_message("✅ Rynek transferowy został zamknięty!", ephemeral=True)

@rynek_slash_group.command(name="zaplanuj_zamkniecie", description="Zaplanuj automatyczne zamknięcie rynku transferowego")
@app_commands.describe(termin="Data i godzina (np. 20.09.2026 18:00 lub 2h, 3d)")
async def slash_rynek_plan_close(interaction: discord.Interaction, termin: str):
    if not (interaction.user.guild_permissions.administrator or is_federation(interaction.user)):
        return await interaction.response.send_message("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.", ephemeral=True)
    dt_str = parse_schedule_datetime(termin)
    if not dt_str:
        return await interaction.response.send_message("❌ Nieprawidłowy format daty! Użyj np. `20.09.2026 18:00` lub `2h`, `3d`.", ephemeral=True)
    curr = database.get_market_state()
    database.set_market_status(curr.get("status", "OPEN"), scheduled_close=dt_str)
    await announce_market_change(
        interaction.guild,
        f"⏰ **ZAPLANOWANO ZAMKNIĘCIE OKIENKA TRANSFEROWEGO!**\n"
        f"> Zamknięcie nastąpi: {format_expiry_discord(dt_str)}"
    )
    await interaction.response.send_message(f"✅ Zaplanowano zamknięcie rynku na: `{dt_str}` ({format_expiry_discord(dt_str)}).", ephemeral=True)

@rynek_slash_group.command(name="zaplanuj_otwarcie", description="Zaplanuj automatyczne otwarcie rynku transferowego")
@app_commands.describe(termin="Data i godzina (np. 20.09.2026 18:00 lub 2h, 3d)")
async def slash_rynek_plan_open(interaction: discord.Interaction, termin: str):
    if not (interaction.user.guild_permissions.administrator or is_federation(interaction.user)):
        return await interaction.response.send_message("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.", ephemeral=True)
    dt_str = parse_schedule_datetime(termin)
    if not dt_str:
        return await interaction.response.send_message("❌ Nieprawidłowy format daty! Użyj np. `20.09.2026 18:00` lub `2h`, `3d`.", ephemeral=True)
    curr = database.get_market_state()
    database.set_market_status(curr.get("status", "OPEN"), scheduled_open=dt_str)
    await announce_market_change(
        interaction.guild,
        f"🔓 **ZAPLANOWANO OTWARCIE OKIENKA TRANSFEROWEGO!**\n"
        f"> Otwarcie nastąpi: {format_expiry_discord(dt_str)}"
    )
    await interaction.response.send_message(f"✅ Zaplanowano otwarcie rynku na: `{dt_str}` ({format_expiry_discord(dt_str)}).", ephemeral=True)

bot.tree.add_group(rynek_slash_group)


# ─── TRADYCYJNE KOMENDY PREFIXOWE: !RYNEK ───
@bot.group(name="rynek", invoke_without_command=True)
async def rynek_prefix_group(ctx):
    """Wyświetla aktualny status okienka transferowego."""
    embed = build_market_status_embed()
    await ctx.reply(embed=embed)

@rynek_prefix_group.command(name="status")
async def rynek_prefix_status(ctx):
    embed = build_market_status_embed()
    await ctx.reply(embed=embed)

@rynek_prefix_group.command(name="otworz")
async def rynek_prefix_otworz(ctx):
    if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
        return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
    database.set_market_status("OPEN", scheduled_open="")
    await announce_market_change(
        ctx.guild,
        "🔓 **RYNEK TRANSFEROWY ZOSTAŁ OTWARTY!**\n"
        "> Zarząd Federacji otworzył okienko transferowe!\n"
        "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało odblokowane."
    )
    await ctx.reply("✅ Rynek transferowy został otwarty!")

@rynek_prefix_group.command(name="zamknij")
async def rynek_prefix_zamknij(ctx):
    if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
        return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
    database.set_market_status("CLOSED", scheduled_close="")
    await announce_market_change(
        ctx.guild,
        "🔒 **RYNEK TRANSFEROWY ZOSTAŁ ZAMKNIĘTY!**\n"
        "> Zarząd Federacji zamknął okienko transferowe.\n"
        "> Składanie wniosków transferowych, kontraktowych i wypożyczeń zostało zablokowane."
    )
    await ctx.reply("✅ Rynek transferowy został zamknięty!")

@rynek_prefix_group.command(name="zaplanuj_zamkniecie")
async def rynek_prefix_plan_close(ctx, *, termin: str):
    if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
        return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
    dt_str = parse_schedule_datetime(termin)
    if not dt_str:
        return await ctx.reply("❌ Nieprawidłowy format daty! Użyj np. `20.09.2026 18:00` lub `2h`, `3d`.")
    curr = database.get_market_state()
    database.set_market_status(curr.get("status", "OPEN"), scheduled_close=dt_str)
    await announce_market_change(
        ctx.guild,
        f"⏰ **ZAPLANOWANO ZAMKNIĘCIE OKIENKA TRANSFEROWEGO!**\n"
        f"> Zamknięcie nastąpi: {format_expiry_discord(dt_str)}"
    )
    await ctx.reply(f"✅ Zaplanowano zamknięcie rynku na: `{dt_str}` ({format_expiry_discord(dt_str)}).")

@rynek_prefix_group.command(name="zaplanuj_otwarcie")
async def rynek_prefix_plan_open(ctx, *, termin: str):
    if not (ctx.author.guild_permissions.administrator or is_federation(ctx.author)):
        return await ctx.reply("❌ Brak uprawnień. Tylko Zarząd Federacji / Administrator.")
    dt_str = parse_schedule_datetime(termin)
    if not dt_str:
        return await ctx.reply("❌ Nieprawidłowy format daty! Użyj np. `20.09.2026 18:00` lub `2h`, `3d`.")
    curr = database.get_market_state()
    database.set_market_status(curr.get("status", "OPEN"), scheduled_open=dt_str)
    await announce_market_change(
        ctx.guild,
        f"🔓 **ZAPLANOWANO OTWARCIE OKIENKA TRANSFEROWEGO!**\n"
        f"> Otwarcie nastąpi: {format_expiry_discord(dt_str)}"
    )
    await ctx.reply(f"✅ Zaplanowano otwarcie rynku na: `{dt_str}` ({format_expiry_discord(dt_str)}).")


# ─── BOT START / RESTART (PERSISTENT VIEWS & TREE SYNC) ───
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

    # Synchronizacja Slash Commands
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            synced_guild = await bot.tree.sync(guild=guild_obj)
            print(f"[on_ready] Zsynchronizowano {len(synced_guild)} slash commands dla gildii {GUILD_ID}.")
        synced_global = await bot.tree.sync()
        print(f"[on_ready] Zsynchronizowano {len(synced_global)} globalnych slash commands.")
    except Exception as e:
        print(f"[on_ready] Błąd synchronizacji slash commands: {e}")

    # Uruchomienie zadania sprawdzającego kontrakty i harmonogram rynku
    if not expirations_task.is_running():
        expirations_task.start()

    print(f"[on_ready] Bot Federacji zalogowany jako: {bot.user} | Guild ID: {GUILD_ID or 'auto'}")


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("BŁĄD: Zmienna środowiskowa DISCORD_TOKEN nie została ustawiona!")
    else:
        bot.run(DISCORD_TOKEN)
