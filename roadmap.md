# ROADMAP — Bot Ligi Piłkarskiej Discord

## Opis projektu
Bot Discord zarządzający ligą piłkarską. Obsługuje rejestrację klubów i zawodników, transfery, wypożyczenia, kontrakty i rynek transferowy. Baza: SQLite (liga.db). Hosting: bot-hosting.net (Docker, Python 3.14).

## Architektura plików

### `config.py`
Konfiguracja środowiskowa — tokeny, ID ról i kanałów Discord, limity ligi. Czyta z .env lub zmiennych środowiskowych. NIE importuje bazy danych.

### `main.py`
Punkt wejścia bota. Inicjalizuje discord.py Bot, ładuje rozszerzenia (Cogs), rejestruje trwałe widoki (Views) z bazy danych, uruchamia zadanie tła. Zawiera tylko `!setup_panel` i `on_ready`.

### `database/` — moduł bazy danych
- `core.py` — połączenie SQLite, definicje tabel, migracje, reset sezonu, backup, statystyki
- `clubs.py` — CRUD klubów (add/get/update/rebrand)
- `players.py` — CRUD zawodników i kontraktów
- `applications.py` — CRUD wniosków transferowych, CAS (try_claim), zgody stron
- `free_agents.py` — giełda wolnych agentów
- `history.py` — historia transferów zawodnika
- `settings.py` — ustawienia ligi, licznik ticketów, harmonogram rynku
- `__init__.py` — re-eksport wszystkich funkcji (backward-compatible API)

### `cogs/` — rozszerzenia bota (Cogs)
- `admin.py` — komendy administracyjne: `/reset`, `/reset_sezon`, `!backup_db`, `!db_stats`
- `market.py` — zarządzanie rynkiem: `/rynek otworz/zamknij/zaplanuj`, `!rynek otworz/zamknij`

### `services/ticket_flows.py`
Logika procesów ligowych. Każdy proces to async def:
- `proces_rejestracji_klubu()` — dialog Q&A przez kanał ticket
- `proces_podpisania()` — podpisanie wolnego agenta
- `proces_transferu()` — transfer zawodnika między klubami
- `proces_wypozyczenia()` — wypożyczenie zawodnika
- `proces_aneksu()` — przedłużenie/zmiana kontraktu
- `proces_rozwiazania()` — rozwiązanie kontraktu
- `proces_zarzadzania_klubem()` — rebrand, zmiana właściciela/zarządu

### `views/`
- `main_panel.py` — `WidokPaneluGlownego` — przyciski Biura Federacji
- `market_panel.py` — `WidokRynkuTransferowego` — przyciski Rynku (Szukam Klubu/Zawodnika/Składy)
- `application_view.py` — `ForumApplicationView` — widok wątku na forum z przyciskami Zgody i Federacji
- `confirmation.py` — `WniosekConfirmView` — potwierdzenie/anulowanie wniosku w tickecie

### `tasks/expirations.py`
Zadanie tła (co 30 sekund). Sprawdza:
1. Harmonogram rynku — czy czas zamknięcia/otwarcia już minął
2. Wygasające kontrakty — wysyła ostrzeżenia 7d/3d/1d przed i po wygaśnięciu

### `utils/helpers.py`
Funkcje pomocnicze:
- Walidacja (is_valid_tag, clean_tag, extract_ids)
- Uprawnienia (is_federation, is_club_board_or_owner)
- Parsowanie dat (parse_expiry_date, parse_schedule_datetime)
- Formatowanie Discord Timestamp (format_expiry_discord, format_schedule_discord)
- Pomocnicze Discord (get_or_fetch_member, has_open_ticket, get_komunikaty_channel)
- UI (build_squad_bar, ping_representatives)

### `tests/`
- `test_database.py` — testy jednostkowe bazy danych (CRUD, granice, kaskady)
- `test_helpers.py` — testy helperów i parserów
- `test_flows.py` — testy logiki biznesowej i blokad
- `test_league.py` — ogólne testy integracyjne

## Kluczowe reguły biznesowe
1. Limit 3 graczy w klubie (MAX_PLAYERS_PER_CLUB)
2. Gracz może mieć tylko jeden aktywny kontrakt
3. Transfer wymaga bycia w zarządzie klubu kupującego (is_club_board_or_owner)
4. Federacja ma nadrzędne prawo jedną decyzją (cb_fed_accept / cb_fed_reject)
5. Rynek można otworzyć/zamknąć manualnie lub zaplanować czas
6. Baza automatycznie resetuje się do sezonu 2026/27 przy starcie jeśli brak flagi season_initialized

## ID Kanałów i Ról
- ROLE_FEDERACJA_ID — rola Zarządu Federacji (config.py)
- ROLA_WZORZEC_ID — wzorcowa rola gracza (config.py)
- CHANNEL_FORUM_ID — forum gdzie trafiają wnioski transferowe (config.py)
- CHANNEL_KOMUNIKATY_ID — kanał z oficjalnymi komunikatami ligi (config.py)

## Tryby używania (cheat sheet)
- `!setup_panel` — wysyła panele (Biuro Federacji + Rynek) do kanału
- `/reset` lub `!reset_sezon` — reset bazy na nowy sezon (admin/federacja)
- `/rynek otworz` lub `!rynek otworz` — otwarcie rynku transferowego
- `/rynek zaplanuj_zamkniecie 20.09.2026 18:00` — planowe zamknięcie
- `!backup_db` — eksport bazy SQLite jako plik
- `!db_stats` — statystyki ligi
