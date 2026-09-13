# ROADMAP — Bot Federacji Siatkówki Stołowej (FSS)

## Opis projektu
Bot Discord zarządzający Federacją Siatkówki Stołowej (w skrócie FSS). Obsługuje rejestrację klubów i zawodników, transfery, wypożyczenia, kontrakty i rynek transferowy. Baza: SQLite (liga.db). Hosting: bot-hosting.net (Docker, Python 3.14).

## Architektura plików

### `config.py`
Konfiguracja środowiskowa — tokeny, ID ról i kanałów Discord, limity ligi. Czyta z .env lub zmiennych środowiskowych. NIE importuje bazy danych.

### `utils/league_config.py`
Dynamiczna konfiguracja FSS (DB-first z fallbackiem na env). Zapewnia natychmiastowe zmiany w locie bez restartu bota dla limitów graczy, kanałów, ról i nazwy organizacji.

### `main.py`
Punkt wejścia bota. Inicjalizuje discord.py Bot, ładuje rozszerzenia (Cogs), rejestruje trwałe widoki (Views) z bazy danych, uruchamia zadanie tła. Zawiera tylko `!setup_panel` i `on_ready`.


### `database/` — moduł bazy danych
- `core.py` — połączenie SQLite, definicje tabel, migracje, modularne resety (reset_all, reset_clubs, reset_contracts, reset_applications, reset_market, reset_setup), backup, statystyki
- `clubs.py` — CRUD klubów (add/get/update/rebrand/delete_club)
- `players.py` — CRUD zawodników i kontraktów
- `applications.py` — CRUD wniosków transferowych, CAS (try_claim), zgody stron
- `free_agents.py` — giełda wolnych agentów
- `history.py` — historia transferów zawodnika
- `settings.py` — ustawienia ligi, licznik ticketów, harmonogram rynku
- `__init__.py` — re-eksport wszystkich funkcji (backward-compatible API)

### `cogs/` — rozszerzenia bota (Cogs)
- `admin.py` — komendy administracyjne: modułowa grupa `/reset` (`wszystko`, `kluby`, `kontrakty`, `wnioski`, `rynek`, `setup`), komendy prefixowe `!reset [zakres]`, `!backup_db`, `!db_stats`
- `market.py` — zarządzanie rynkiem: `/rynek otworz/zamknij/zaplanuj`, `!rynek otworz/zamknij`
- `setup_cog.py` — nowoczesny panel konfiguracyjny FSS (/setup)

### `services/ticket_flows.py`
Logika procesów ligowych. Każdy proces to async def:
- `proces_rejestracji_klubu()` — dialog Q&A przez kanał ticket
- `proces_podpisania()` — podpisanie wolnego agenta (Zarząd Federacji może podpisywać za dowolny klub)
- `proces_transferu()` — transfer zawodnika między klubami
- `proces_wypozyczenia()` — wypożyczenie zawodnika
- `proces_aneksu()` — przedłużenie/zmiana kontraktu
- `proces_rozwiazania()` — rozwiązanie kontraktu
- `proces_zarzadzania_klubem()` — rebrand, zmiana władz lub natychmiastowa likwidacja klubu (Zarząd Federacji ma wgląd i wybór każdego klubu)

### `views/`
- `main_panel.py` — `WidokPaneluGlownego` — przyciski Biura Federacji
- `market_panel.py` — `WidokRynkuTransferowego` — przyciski Rynku (Szukam Klubu/Zawodnika/Składy)
- `application_view.py` — `ForumApplicationView` — widok wątku na forum z przyciskami Zgody, Federacji i obsługą likwidacji (USUNIECIE_KLUBU)
- `confirmation.py` — `WniosekConfirmView` — potwierdzenie/anulowanie wniosku w tickecie

### `tasks/expirations.py`
Zadanie tła (co 30 sekund). Sprawdza:
1. Harmonogram rynku — czy czas zamknięcia/otwarcia już minął
2. Wygasające kontrakty — wysyła ostrzeżenia 7d/3d/1d przed i po wygaśnięciu

### `utils/helpers.py`
Funkcje pomocnicze:
- Walidacja (is_valid_tag, clean_tag, extract_ids)
- Uprawnienia (is_federation, is_club_board_or_owner z override dla Zarządu Federacji i Administratorów)
- Parsowanie dat (parse_expiry_date, parse_schedule_datetime)
- Formatowanie Discord Timestamp (format_expiry_discord, format_schedule_discord)
- Pomocnicze Discord (get_or_fetch_member, has_open_ticket, get_komunikaty_channel)
- UI (build_squad_bar, ping_representatives)

### `tests/`
- `test_database.py` — testy jednostkowe bazy danych (CRUD, delete_club, granularne resety, granice, kaskady)
- `test_helpers.py` — testy helperów i parserów
- `test_flows.py` — testy logiki biznesowej, blokad, likwidacji klubów i uprawnień federacji
- `test_league.py` — ogólne testy integracyjne

## Kluczowe reguły biznesowe
1. Limit graczy w klubie (konfigurowalny przez /setup, domyślnie 3)
2. Gracz może mieć tylko jeden aktywny kontrakt
3. Transfer wymaga bycia w zarządzie klubu kupującego LUB roli Zarządu Federacji
4. Federacja ma nadrzędne prawo jednoosobowej decyzji oraz zarządzania/podpisywania za dowolny klub
5. Rynek można otworzyć/zamknąć manualnie lub zaplanować czas
6. Baza automatycznie inicjalizuje się do sezonu 2026/27 przy starcie jeśli brak flagi season_initialized

## ID Kanałów i Ról
- ROLE_FEDERACJA_ID — rola Zarządu Federacji (config.py)
- ROLA_WZORZEC_ID — wzorcowa rola gracza (config.py)
- CHANNEL_FORUM_ID — forum gdzie trafiają wnioski transferowe (config.py)
- CHANNEL_KOMUNIKATY_ID — kanał z oficjalnymi komunikatami ligi (config.py)

## Tryby używania (cheat sheet)
- `!setup_panel` — wysyła panele FSS (Biuro Federacji + Rynek) do kanału
- `/reset wszystko` (lub `!reset wszystko`) — całkowite usunięcie wszystkich danych (wraz z panelem /setup)
- `/reset kluby` (lub `!reset kluby`) — usunięcie klubów, kontraktów i wniosków (zachowuje /setup i wolnych agentów)
- `/reset kontrakty` (lub `!reset kontrakty`) — wyczyszczenie graczy, kontraktów i wolnych agentów (zachowuje kluby)
- `/reset wnioski` (lub `!reset wnioski`) — wyczyszczenie wniosków i reset licznika ticketów do #001
- `/reset rynek` (lub `!reset rynek`) — otwarcie rynku, usunięcie harmonogramu i wyczyszczenie wolnych agentów
- `/reset setup` (lub `!reset setup`) — przywrócenie domyślnej konfiguracji panelu /setup
- `/setup panel` — interaktywny panel administracyjny z przyciskami (rynek, status)
- `/setup liga max_graczy <liczba>` — dynamiczna zmiana limitu zawodników w klubie
- `/setup rynek otworz / zamknij / zaplanuj_zamkniecie / zaplanuj_otwarcie` — rynek transferowy
- `!rynek` — szybki podgląd statusu rynku
- `!backup_db` — eksport bazy SQLite jako plik
- `!db_stats` — statystyki bazy

