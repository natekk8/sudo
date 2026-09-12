import os
import tempfile
from datetime import datetime
import discord
from discord.ext import commands
from config import DISCORD_TOKEN, GUILD_ID, MAX_PLAYERS_PER_CLUB
import database
from views.main_panel import WidokPaneluGlownego
from views.market_panel import WidokRynkuTransferowego
from views.application_view import ForumApplicationView
from tasks.expirations import setup_expirations_task
from utils.helpers import (
    is_federation, send_dm, build_squad_bar, format_expiry_discord,
    clean_tag
)

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
            "Zarejestruj swój profil (pozycja + platforma) na giełdzie wolnych agentów. "
            "Ponowne kliknięcie usunie Cię z listy.\n\n"
            "**🔍 Szukam Zawodnika**\n"
            "Przeglądaj profile graczy bez klubu, z pozycjami i platformami.\n\n"
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


# ─── KOMENDY INFORMACYJNE DLA WSZYSTKICH ───
@bot.command()
async def liga_status(ctx):
    """Zwraca estetyczny przegląd stanu ligi i zapełnienia kadr klubowych."""
    clubs = database.get_all_clubs()
    stats = database.get_league_stats()

    total_capacity = len(clubs) * MAX_PLAYERS_PER_CLUB
    total_contracted = stats["players"]

    embed = discord.Embed(title="🏆 Stan Ligi i Zapełnienie Drużyn", color=0x3498db)
    summary = (
        f"• Zarejestrowane kluby: **{stats['clubs']}**\n"
        f"• Zakontraktowani gracze: **{total_contracted}/{total_capacity}** miejsc\n"
        f"• Wolni agenci na giełdzie: **{stats['free_agents']}**\n"
        f"• Oczekujące wnioski w Biurze: **{stats['pending_applications']}**"
    )
    embed.add_field(name="Podsumowanie", value=summary, inline=False)

    if clubs:
        club_lines = []
        for c in clubs:
            cnt = database.get_club_player_count(c["tag"])
            bar = build_squad_bar(cnt, MAX_PLAYERS_PER_CLUB)
            club_lines.append(f"**{c['name']}** (`{c['tag']}`) {bar}")
        embed.add_field(name="Kadry Zespołów", value="\n".join(club_lines), inline=False)
    else:
        embed.add_field(name="Kadry Zespołów", value="*Brak zarejestrowanych klubów.*", inline=False)

    embed.set_footer(text="Liga Federacji • Użyj !klub <TAG> aby zobaczyć szczegóły")
    await ctx.reply(embed=embed)


@bot.command()
async def klub(ctx, tag: str = None):
    """Wyświetla szczegółowy profil klubu i jego zawodników: !klub <TAG>."""
    if not tag:
        return await ctx.reply("ℹ️ Użycie: `!klub <TAG>` (np. `!klub LAZ`).")

    c_tag = clean_tag(tag)
    c = database.get_club(c_tag)
    if not c:
        return await ctx.reply(f"❌ Nie znaleziono klubu o skrócie `{c_tag}`.")

    players = database.get_club_players(c_tag)
    count = len(players)

    embed = discord.Embed(title=f"⚽ {c['name']} (`{c_tag}`)", color=0x2b2d31)
    embed.add_field(name="Stan kadry", value=build_squad_bar(count, MAX_PLAYERS_PER_CLUB), inline=False)

    if players:
        p_lines = []
        for p in players:
            name_d = f"<@{p['discord_id']}>" if p.get("discord_id") else f"**{p['name']}**"
            typ = "⏱️ Wyp." if p.get("contract_type") == "WYPOZYCZENIE" else "📄"
            expires = format_expiry_discord(p.get("expires_at"))
            klauz = p.get("clause", "Brak")
            p_lines.append(f"{typ} {name_d} · do {expires} · Klauzula: `{klauz}`")
        embed.add_field(name="Zawodnicy", value="\n".join(p_lines), inline=False)
    else:
        embed.add_field(name="Zawodnicy", value="*Brak zarejestrowanych zawodników.*", inline=False)

    # Władze klubu
    board_info = []
    if c.get("founder_txt"): board_info.append(f"Założyciel: {c['founder_txt']}")
    if c.get("board_txt") and c["board_txt"].lower() != "brak":
        board_info.append(f"Zarząd: {c['board_txt']}")
    if board_info:
        embed.add_field(name="Władze klubu", value="\n".join(board_info), inline=False)

    # Ostatnie 3 ruchy transferowe
    history = database.get_player_transfer_history("", None)
    club_history = [
        h for h in history
        if (h.get("from_club") and h["from_club"].upper() == c_tag)
        or (h.get("to_club") and h["to_club"].upper() == c_tag)
    ][:3]
    if club_history:
        h_lines = []
        for h in club_history:
            f_c = h.get("from_club") or "Wolny Agent"
            t_c = h.get("to_club") or "Wolny Agent"
            d_str = h.get("date", "")[:10]
            h_lines.append(f"• `{d_str}` {h['player_name']}: {f_c} ➔ **{t_c}** ({h['transfer_type']})")
        embed.add_field(name="Ostatnie ruchy", value="\n".join(h_lines), inline=False)

    embed.set_footer(text="Liga Federacji")
    await ctx.reply(embed=embed)


# ─── MONITOR "RAGE-QUIT / GHOSTING" ───
@bot.event
async def on_member_remove(member: discord.Member):
    """Wykrywa opuszczenie serwera przez gracza – czyści giełdę i powiadamia zarząd."""
    # 1. Jeśli był na Giełdzie Wolnych Agentów – usuń go
    if database.is_free_agent(member.id):
        database.remove_free_agent(member.id)
        print(f"[on_member_remove] Usunięto {member.display_name} z giełdy wolnych agentów.")

    # 2. Jeśli miał aktywny kontrakt w klubie – ostrzeż zarząd klubu
    player = database.get_player_by_discord_id(member.id)
    if player and player.get("club_tag"):
        c_tag = player["club_tag"]
        club = database.get_club(c_tag)
        rep_id = club.get("reprezentant_dc") if club else None
        board_ids = club.get("board_ids", []) if club else []
        targets = set(filter(None, [rep_id] + board_ids))

        warning_msg = (
            f"⚠️ **Pilne powiadomienie!**\n"
            f"> Gracz **{member.display_name}** (`{player.get('name')}`) opuścił serwer Discord ligi!\n"
            f"> Nadal figuruje jako zawodnik Twojego klubu **`{c_tag}`** i blokuje slot w kadrze.\n"
            f"> Jeśli gracz nie wraca, złóż wniosek o **Rozwiązanie Dyscyplinarne** w Biurze Federacji."
        )
        for uid in targets:
            await send_dm(bot, uid, warning_msg)


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
