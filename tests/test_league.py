"""
test_league.py – Testy jednostkowe bota ligowego.
Uruchom: python -m unittest tests/test_league.py -v
"""
import unittest
import os
import sys
import sqlite3
from datetime import datetime, timedelta

# Zmień DB_PATH na tymczasowy, żeby nie nadpisywać produkcyjnej bazy
os.environ["DB_PATH"] = ":memory:"
os.environ["DISCORD_TOKEN"] = "test"
os.environ["GUILD_ID"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from utils.helpers import clean_tag, extract_ids, parse_expiry_date, parse_amount, validate_amount_input, build_squad_bar


def setup_fresh_db():
    """Resetuje baz danych in-memory przed każdym testem."""
    # init_db wewnętrznie otwiera połączenie według DB_PATH
    database.init_db()


class TestCleanTag(unittest.TestCase):
    def test_uppercase_and_strip(self):
        self.assertEqual("LAZ", clean_tag("  laz  "))

    def test_empty(self):
        self.assertEqual("", clean_tag(""))

    def test_none(self):
        self.assertEqual("", clean_tag(None))


class TestExtractIds(unittest.TestCase):
    def test_single_mention(self):
        self.assertEqual([123456789], extract_ids("<@123456789>"))

    def test_multiple_mentions(self):
        self.assertEqual([111, 222], extract_ids("<@111> <@222>"))

    def test_no_mentions(self):
        self.assertEqual([], extract_ids("Brak"))

    def test_nickname_mention(self):
        self.assertEqual([999], extract_ids("<@!999>"))


class TestParseAmount(unittest.TestCase):
    def test_plain_integer(self):
        self.assertEqual(5000, parse_amount("5000"))

    def test_spaced_integer(self):
        self.assertEqual(1500, parse_amount("1 500"))

    def test_comma_separator(self):
        self.assertEqual(1500, parse_amount("1,500"))

    def test_decimal_rejected(self):
        """Kwota 1.5 mln powinna zwrócić 0 (odrzucona)."""
        self.assertEqual(0, parse_amount("1.5"))

    def test_text_rejected(self):
        self.assertEqual(0, parse_amount("Brak"))

    def test_empty_rejected(self):
        self.assertEqual(0, parse_amount(""))


class TestValidateAmountInput(unittest.TestCase):
    def test_valid_number(self):
        self.assertTrue(validate_amount_input("5000"))

    def test_brak_keyword(self):
        self.assertTrue(validate_amount_input("Brak"))

    def test_brak_case_insensitive(self):
        self.assertTrue(validate_amount_input("BRAK"))

    def test_decimal_invalid(self):
        self.assertFalse(validate_amount_input("1.5mln"))

    def test_empty_invalid(self):
        self.assertFalse(validate_amount_input(""))


class TestParseExpiryDate(unittest.TestCase):
    def test_days_format(self):
        result = parse_expiry_date("30")
        self.assertIsNotNone(result)
        dt = datetime.strptime(result, "%Y-%m-%d %H:%M:%S")
        days_diff = (dt - datetime.now()).days
        self.assertAlmostEqual(days_diff, 29, delta=1)  # 29-30 dni różnicy

    def test_days_with_unit(self):
        result = parse_expiry_date("14 dni")
        self.assertIsNotNone(result)

    def test_date_format_dot(self):
        future = (datetime.now() + timedelta(days=100)).strftime("%d.%m.%Y")
        result = parse_expiry_date(future)
        self.assertIsNotNone(result)

    def test_past_date_rejected(self):
        self.assertIsNone(parse_expiry_date("01.01.2000"))

    def test_invalid_format(self):
        self.assertIsNone(parse_expiry_date("jutro"))

    def test_zero_days_rejected(self):
        self.assertIsNone(parse_expiry_date("0"))


class TestBuildSquadBar(unittest.TestCase):
    def test_empty_squad(self):
        bar = build_squad_bar(0, 3)
        self.assertIn("0/3", bar)
        self.assertIn("□□□", bar)

    def test_full_squad(self):
        bar = build_squad_bar(3, 3)
        self.assertIn("3/3", bar)
        self.assertIn("■■■", bar)
        self.assertIn("Kadra pełna", bar)

    def test_partial_squad(self):
        bar = build_squad_bar(2, 3)
        self.assertIn("2/3", bar)
        self.assertIn("■■□", bar)


class TestDatabase(unittest.TestCase):
    def setUp(self):
        import tempfile
        # Używamy tymczasowego pliku per-test (cross-platform, działa na Windows i Linux)
        fd, self.test_db = tempfile.mkstemp(suffix=".db", prefix="test_liga_")
        os.close(fd)
        os.remove(self.test_db)  # sqlite3 sam stworzy plik
        database.DB_PATH = self.test_db
        database.init_db()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_add_and_get_club(self):
        database.add_club("TST", "Test Club", 1001, 1002, board_ids=[500])
        c = database.get_club("TST")
        self.assertIsNotNone(c)
        self.assertEqual(c["name"], "Test Club")
        self.assertIn(500, c["board_ids"])

    def test_get_club_case_insensitive(self):
        database.add_club("ABC", "Alpha Beta Club", 1, 2)
        self.assertIsNotNone(database.get_club("abc"))
        self.assertIsNotNone(database.get_club("ABC"))

    def test_add_and_get_player(self):
        database.add_club("PLY", "Player Club", 1, 2)
        database.add_or_update_player("Jan Kowalski", 987, "PLY", "PLY", "5000", "TRANSFER", "2027-01-01 00:00:00")
        p = database.get_player("Jan Kowalski")
        self.assertIsNotNone(p)
        self.assertEqual(p["club_tag"], "PLY")
        self.assertEqual(p["discord_id"], 987)

    def test_player_count(self):
        database.add_club("CNT", "Count Club", 1, 2)
        self.assertEqual(0, database.get_club_player_count("CNT"))
        database.add_or_update_player("A1", 1, "CNT", "CNT", "Brak", "TRANSFER", "2027-01-01 00:00:00")
        database.add_or_update_player("A2", 2, "CNT", "CNT", "Brak", "TRANSFER", "2027-01-01 00:00:00")
        self.assertEqual(2, database.get_club_player_count("CNT"))

    def test_contract_theft_prevention(self):
        """Weryfikacja wykrywania gracza już w innym klubie."""
        database.add_club("FC1", "First Club", 1, 2)
        database.add_club("FC2", "Second Club", 3, 4)
        database.add_or_update_player("Złodziej", 777, "FC1", "FC1", "Brak", "TRANSFER", "2027-01-01 00:00:00")

        # Sprawdzenie is_player_under_contract
        existing = database.is_player_under_contract("Złodziej", 777)
        self.assertIsNotNone(existing)
        self.assertEqual(existing["club_tag"], "FC1")
        # Weryfikacja przynależności do innego klubu
        self.assertNotEqual(existing.get("club_tag", "").upper(), "FC2")

    def test_transfer_history_recording(self):
        database.add_transfer_history("Gracz X", 123, "STA", "DST", "TRANSFER", "10000")
        database.add_transfer_history("Gracz X", 123, "DST", None, "WYGASNIECIE", None)
        history = database.get_player_transfer_history("Gracz X", 123)
        self.assertEqual(len(history), 2)
        types = {h["transfer_type"] for h in history}
        self.assertIn("TRANSFER", types)
        self.assertIn("WYGASNIECIE", types)


    def test_free_agent_registration(self):
        database.register_free_agent(555, "Nowy Agent")
        self.assertTrue(database.is_free_agent(555))
        agents = database.get_all_free_agents()
        self.assertTrue(any(a["discord_id"] == 555 for a in agents))

    def test_free_agent_removal(self):
        database.register_free_agent(666, "Stary Agent")
        database.remove_free_agent(666)
        self.assertFalse(database.is_free_agent(666))

    def test_duplicate_free_agent_updates(self):
        """Duplikat REPLACE – zawodnik nadpisuje swój wpis."""
        database.register_free_agent(444, "Duplikat Gracz")
        database.register_free_agent(444, "Duplikat Gracz Nowa Nazwa")
        agents = database.get_all_free_agents()
        agents_for_id = [a for a in agents if a["discord_id"] == 444]
        self.assertEqual(len(agents_for_id), 1)  # tylko jeden wpis

    def test_loan_return_restores_parent_contract(self):
        """Powrót z wypożyczenia przywraca datę kontraktu macierzystego."""
        database.add_club("HOME", "Home Club", 1, 2)
        database.add_club("LOAN", "Loan Club", 3, 4)
        parent_date = "2027-06-30 23:59:59"
        loan_date = "2027-01-31 23:59:59"

        database.add_or_update_player(
            "Loański Gracz", 888, "LOAN", "HOME",
            "Bez zmian", "WYPOZYCZENIE", loan_date,
            parent_contract_expires_at=parent_date
        )
        p = database.get_player("Loański Gracz")
        self.assertEqual(p["parent_contract_expires_at"], parent_date)
        self.assertEqual(p["expires_at"], loan_date)

        # Symulacja powrotu z wypożyczenia
        database.add_or_update_player(
            "Loański Gracz", 888, "HOME", "HOME",
            "Bez zmian", "TRANSFER", parent_date,
            parent_contract_expires_at=None
        )
        p_after = database.get_player("Loański Gracz")
        self.assertEqual(p_after["club_tag"], "HOME")
        self.assertEqual(p_after["expires_at"], parent_date)
        self.assertIsNone(p_after["parent_contract_expires_at"])

    def test_warning_flags(self):
        database.add_club("WRN", "Warning Club", 1, 2)
        database.add_or_update_player("Warnowany", 999, "WRN", "WRN", "Brak", "TRANSFER", "2027-01-01 00:00:00")
        p = database.get_player("Warnowany")
        self.assertEqual(p["warned_7d"], 0)
        database.set_player_warning_flag("Warnowany", "warned_7d")
        p2 = database.get_player("Warnowany")
        self.assertEqual(p2["warned_7d"], 1)

    def test_set_application_status_with_rejected_by(self):
        database.add_club("APL", "Apply Club", 1, 2)
        app_id = database.create_application(
            app_type="PODPISANIE", applicant_id=1,
            player_name="Test Gracz", target_club="APL", expires_at="2027-01-01 00:00:00"
        )
        database.set_application_status(app_id, "REJECTED", rejected_by="Zarząd XYZ")
        app = database.get_application(app_id)
        self.assertEqual(app["status"], "REJECTED")
        self.assertIn("XYZ", app["rejected_by"])


if __name__ == "__main__":
    unittest.main()
