import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from config import DISCORD_TOKEN, GUILD_ID
import database
import utils.league_config as league_config
from views.main_panel import WidokTransferowIKontraktow, WidokAdministracjiKlubow
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

from utils.helpers import set_bot
set_bot(bot)

expirations_task = setup_expirations_task(bot, guild_id=GUILD_ID or None)


@bot.tree.command(name="setup_panel", description="[ADMIN] Wysyła panele FSS na ten kanał.")
@app_commands.default_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction):
    """
    Wysyła TRZY panele FSS:
    1️⃣ Transfery i Kontrakty
    2️⃣ Rynek Transferowy
    3️⃣ Administracja Klubów
    """
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Tylko administratorzy mogą użyć tej komendy.", ephemeral=True)

    await interaction.response.send_message("⏳ Wysyłam panele...", ephemeral=True)

    mx = league_config.max_players()
    org_name = league_config.league_name()

    # ── Panel 1: Transfery i Kontrakty ───────────────────────────────────────
    embed1 = discord.Embed(
        title="📋 Biuro Składów i Kontraktów — FSS",
        description=(
            "Oficjalne procedury transferowo-kontraktowe Federacji Siatkówki Stołowej.\n"
            "Kliknięcie przycisku otwiera **dedykowany prywatny ticket**, w którym bot przeprowadzi Cię przez wniosek.\n\n"
            f"**👤 Podpisanie Gracza** · Rejestracja wolnego agenta do klubu (limit: **{mx}** zawodników + opcjonalny 4. zawodnik na 5 dni).\n"
            "**🤝 Wniosek Transferowy / Wymiana** · Kupno zawodnika z innego klubu lub bezpośrednia wymiana z dopłatą.\n"
            "**⏱️ Wypożyczenie** · Czasowe przejście zawodnika do innego klubu z zachowaniem praw macierzystych.\n\n"
            "**📄 Aneks do Umowy** · Przedłużenie wygasającego kontraktu lub modyfikacja klauzuli wykupu.\n"
            "**❌ Rozwiązanie Umowy** · Polubowne zakończenie kontraktu za porozumieniem stron.\n\n"
            "> ℹ️ *Zarząd Federacji może składać i natychmiast zatwierdzać wnioski w imieniu każdego klubu.*"
        ),
        color=0x2b2d31
    )
    embed1.set_footer(text=f"{org_name} • Transfery i Kontrakty")
    await interaction.channel.send(embed=embed1, view=WidokTransferowIKontraktow())

    # ── Panel 2: Rynek Transferowy ───────────────────────────────────────────
    embed2 = discord.Embed(
        title="📊 Rynek Transferowy & Kadry Klubowe — FSS",
        description=(
            "Centralny rynek zawodników, oficjalna lista transferowa i składy drużyn.\n\n"
            "**📝 Zaktualizuj Listę Transferową**\n"
            "» **Zarząd klubu:** wystaw swojego zawodnika na sprzedaż z określoną ceną lub zdejmij go z listy.\n"
            "» **Zarząd Federacji:** pełne uprawnienia do zarządzania listą transferową dowolnego klubu.\n\n"
            "**🔍 Szukam Zawodnika**\n"
            "Przeglądaj oficjalną **Listę Transferową** (posortowaną cenowo) z pełnymi danymi zawodników oraz bazę wolnych agentów.\n\n"
            "**📋 Składy Drużyn**\n"
            "Sprawdź oficjalne kadry wszystkich klubów, statusy zawodników (w tym wystawionych na sprzedaż) i terminy umów."
        ),
        color=0x1e1f22
    )
    embed2.set_footer(text=f"{org_name} • Giełda i Składy")
    await interaction.channel.send(embed=embed2, view=WidokRynkuTransferowego())

    # ── Panel 3: Administracja Klubów ────────────────────────────────────────
    embed3 = discord.Embed(
        title="🏛️ Biuro Federacji Siatkówki Stołowej",
        description=(
            "Oficjalne sprawy administracyjne FSS — rejestracja, zarządzanie klubem oraz ogólny kontakt z Zarządem.\n\n"
            "**📝 Rejestracja Klubu** · Wniosek o utworzenie i dołączenie nowej drużyny do federacji.\n"
            "**⚙️ Zarządzanie Klubem** · Zmiana nazwy, TAGu, właściciela, składu zarządu lub rozwiązanie klubu.\n\n"
            "**📨 Złóż Wniosek Ogólny** · Wszelkie inne sprawy do Federacji (odwołania, przekładanie meczów, zapytania)."
        ),
        color=0x3d5a80
    )
    embed3.set_footer(text=f"{org_name} • Biuro Federacji")
    await interaction.channel.send(embed=embed3, view=WidokAdministracjiKlubow())


@bot.event
async def on_ready():
    bot.add_view(WidokTransferowIKontraktow())
    bot.add_view(WidokAdministracjiKlubow())
    bot.add_view(WidokRynkuTransferowego())

    # Odblokuj wnioski, które mogły utknąć w statusie PROCESSING po restarcie
    try:
        database.reset_stuck_processing_applications()
    except Exception as e:
        print(f"[on_ready] Błąd resetu PROCESSING: {e}")

    # Czyszczenie sierocych kanałów ticketów (rozwiązanie problemu trwałej blokady po restarcie)
    try:
        guild = bot.get_guild(int(GUILD_ID)) if GUILD_ID else (bot.guilds[0] if bot.guilds else None)
        if guild:
            from utils.helpers import TICKET_PREFIXES
            for channel in guild.text_channels:
                if any(channel.name.startswith(p) for p in TICKET_PREFIXES):
                    try:
                        await channel.delete(reason="Czyszczenie sierocych ticketów po restarcie bota.")
                        print(f"[on_ready] Usunięto osierocony ticket: {channel.name}")
                    except Exception as e:
                        print(f"[on_ready] Nie udało się usunąć ticketu {channel.name}: {e}")
    except Exception as e:
        print(f"[on_ready] Błąd podczas czyszczenia ticketów: {e}")

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


@bot.event
async def on_command_error(ctx, error):
    # Ignoruj brakujące komendy prefixowe (np. pomyłki typu !site_panel)
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingPermissions):
        try:
            await ctx.send("❌ Nie posiadasz uprawnień do użycia tej komendy.", delete_after=5)
        except Exception:
            pass
    else:
        print(f"[on_command_error] Błąd komendy {ctx.command}: {error}")


@bot.event
async def on_interaction(interaction: discord.Interaction):
    # Dynamiczny fallback dla przycisków wniosków (custom_id: app:<app_id>:<action>)
    # Jeśli discord.py odrzucił interakcję (unknown view), obsługujemy ją awaryjnie.
    if interaction.type == discord.InteractionType.component:
        cid = interaction.data.get("custom_id", "")
        if cid.startswith("app:"):
            # Dajemy chwilę na obsłużenie przez wbudowany dispatcher widoku discord.py
            await asyncio.sleep(0.05)
            if interaction.response.is_done():
                return

            try:
                parts = cid.split(":")
                if len(parts) >= 3:
                    app_id = int(parts[1])
                    action = parts[2]
                    view = ForumApplicationView(app_id)
                    if interaction.message:
                        try:
                            bot.add_view(view, message_id=interaction.message.id)
                            database.set_application_message(app_id, interaction.channel.id, interaction.message.id)
                        except Exception:
                            pass

                    action_map = {
                        "fed_accept": view.cb_fed_accept,
                        "fed_reject": view.cb_fed_reject,
                        "p_agree": view.cb_player_agree,
                        "pb_agree": view.cb_player_b_agree,
                        "t_agree": view.cb_target_agree,
                        "s_agree": view.cb_source_agree,
                        "party_reject": view.cb_party_reject,
                        "history": view.cb_history,
                    }
                    handler = action_map.get(action)
                    if handler and not interaction.response.is_done():
                        try:
                            await handler(interaction)
                        except discord.errors.HTTPException as err:
                            if err.code == 40060:
                                pass  # Interakcja została już obsłużona
                            else:
                                raise
            except Exception as e:
                print(f"[on_interaction] Błąd dynamicznego dispatchu dla {cid}: {e}")

        elif cid == "rynek_szukam_klubu":
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "ℹ️ **System został zaktualizowany!**\n"
                    "> Przycisk *Dołącz do rezerwy* został wycofany i zastąpiony nowym systemem **Listy Transferowej**.\n"
                    "> Użyj przycisku **Zaktualizuj Listę Transferową** lub poproś administratora o ponowne wysłanie paneli komendą `/setup_panel`.",
                    ephemeral=True
                )


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("BŁĄD: Zmienna środowiskowa DISCORD_TOKEN nie została ustawiona!")
    else:
        bot.run(DISCORD_TOKEN)
