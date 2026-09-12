"""
test_league.py – Testy jednostkowe bota ligowego.
Uruchom: python -m unittest tests/test_league.py -v
"""
import unittest
import os
import sys
import tempfile
import sqlite3
from datetime import datetime, timedelta

# Zmień DB_PATH na tymczasowy, żeby nie nadpisywać produkcyjnej bazy
os.environ["DB_PATH"] = ":memory:"
os.environ["DISCORD_TOKEN"] = "test"
os.environ["GUILD_ID"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from utils.helpers import (
    clean_tag, is_valid_tag, extract_ids, parse_expiry_date,
    parse_amount, validate_amount_input, build_squad_bar, safe_thread_name
)


class TestCleanTag(unittest.TestCase):
    def test_uppercase_and_strip(self):
        self.assertEqual("LAZ", clean_tag("  laz  "))

    def test_empty(self):
        self.assertEqual("", clean_tag(""))

    def test_none(self):
        self.assertEqual("", clean_tag(None))


class TestIsValidTag(unittest.TestCase):
    def test_valid_3_letters(self):
        self.assertTrue(is_valid_tag("LAZ"))

    def test_valid_alphanumeric(self):
        self.assertTrue(is_valid_tag("FC1"))
        self.assertTrue(is_valid_tag("123"))

    def test_invalid_too_short(self):
        self.assertFalse(is_valid_tag("LA"))

    def test_invalid_too_long(self):
        self.assertFalse(is_valid_tag("LAZZ"))

    def test_invalid_special_chars(self):
        self.assertFalse(is_valid_tag("L@Z"))
        self.assertFalse(is_valid_tag("L Z"))

    def test_invalid_empty(self):
        self.assertFalse(is_valid_tag(""))
        self.assertFalse(is_valid_tag(None))


class TestSafeThreadName(unittest.TestCase):
    def test_short_name_unaltered(self):
        self.assertEqual("[LAZ] Nowy Gracz", safe_thread_name("[LAZ] Nowy Gracz"))

    def test_long_name_truncated_to_100(self):
        long_str = "A" * 150
        truncated = safe_thread_name(long_str)
        self.assertEqual(100, len(truncated))
        self.assertEqual("A" * 100, truncated)


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
        self.assertAlmostEqual(days_diff, 29, delta=1)

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
        fd, self.test_db = tempfile.mkstemp(suffix=".db", prefix="test_liga_")
        os.close(fd)
        os.remove(self.test_db)
        database.DB_PATH = self.test_db
        database.init_db()

    def tearDown(self):
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

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
        database.add_club("FC1", "First Club", 1, 2)
        database.add_club("FC2", "Second Club", 3, 4)
        database.add_or_update_player("Złodziej", 777, "FC1", "FC1", "Brak", "TRANSFER", "2027-01-01 00:00:00")

        existing = database.is_player_under_contract("Złodziej", 777)
        self.assertIsNotNone(existing)
        self.assertEqual(existing["club_tag"], "FC1")
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

    def test_free_agents_pagination(self):
        for i in range(30):
            database.register_free_agent(1000 + i, f"Agent_{i}")
        page, total = database.get_free_agents_paginated(limit=25)
        self.assertEqual(total, 30)
        self.assertEqual(len(page), 25)

    def test_loan_return_restores_parent_contract_and_clause(self):
        database.add_club("HOME", "Home Club", 1, 2)
        database.add_club("LOAN", "Loan Club", 3, 4)
        parent_date = "2027-06-30 23:59:59"
        parent_clause_val = "25000"
        loan_date = "2027-01-31 23:59:59"

        database.add_or_update_player(
            "Loański Gracz", 888, "LOAN", "HOME",
            clause=parent_clause_val, contract_type="WYPOZYCZENIE", expires_at=loan_date,
            parent_contract_expires_at=parent_date, parent_clause=parent_clause_val
        )
        p = database.get_player("Loański Gracz")
        self.assertEqual(p["parent_contract_expires_at"], parent_date)
        self.assertEqual(p["parent_clause"], parent_clause_val)
        self.assertEqual(p["expires_at"], loan_date)

        # Powrót z wypożyczenia
        database.add_or_update_player(
            "Loański Gracz", 888, "HOME", "HOME",
            clause=p["parent_clause"], contract_type="TRANSFER", expires_at=parent_date,
            parent_contract_expires_at=None, parent_clause=None
        )
        p_after = database.get_player("Loański Gracz")
        self.assertEqual(p_after["club_tag"], "HOME")
        self.assertEqual(p_after["expires_at"], parent_date)
        self.assertEqual(p_after["clause"], parent_clause_val)
        self.assertIsNone(p_after["parent_clause"])

    def test_warning_flags(self):
        database.add_club("WRN", "Warning Club", 1, 2)
        database.add_or_update_player("Warnowany", 999, "WRN", "WRN", "Brak", "TRANSFER", "2027-01-01 00:00:00")
        p = database.get_player("Warnowany")
        self.assertEqual(p["warned_7d"], 0)
        database.set_player_warning_flag("Warnowany", "warned_7d")
        p2 = database.get_player("Warnowany")
        self.assertEqual(p2["warned_7d"], 1)

    # ── Testy CAS (Compare-And-Swap) – ochrona przed TOCTOU ──
    def test_try_claim_application_for_approval(self):
        database.add_club("CAS", "CAS Club", 1, 2)
        app_id = database.create_application(
            app_type="TRANSFER", applicant_id=10,
            player_name="Gracz CAS", target_club="CAS", source_club="CAS",
            expires_at="2027-01-01 00:00:00"
        )
        # Pierwszy claim powinien się udać i zmienić stan na PROCESSING
        claim1 = database.try_claim_application_for_approval(app_id)
        self.assertIsNotNone(claim1)
        self.assertEqual(claim1["status"], "PENDING")

        app_mid = database.get_application(app_id)
        self.assertEqual(app_mid["status"], "PROCESSING")

        # Drugi równoległy claim na ten sam wniosek musi zwrócić None!
        claim2 = database.try_claim_application_for_approval(app_id)
        self.assertIsNone(claim2)

    def test_revert_application_status(self):
        app_id = database.create_application(
            app_type="TRANSFER", applicant_id=10,
            player_name="Gracz Rollback", target_club="RLB", expires_at="2027-01-01 00:00:00"
        )
        database.try_claim_application_for_approval(app_id)
        # Rollback do PENDING
        database.revert_application_status(app_id, "PENDING")
        app = database.get_application(app_id)
        self.assertEqual(app["status"], "PENDING")

    # ── Test Rebrandingu Klubu ──
    def test_rebrand_club_cascade(self):
        database.add_club("OLD", "Stara Nazwa", 1, 2)
        database.add_or_update_player("Gracz Rebrand", 707, "OLD", "OLD", "5000", "TRANSFER", "2027-01-01 00:00:00")
        database.add_transfer_history("Gracz Rebrand", 707, "OLD", "OLD", "TRANSFER", "5000")

        database.rebrand_club("OLD", "NEW", "Nowa Nazwa")

        # Sprawdź klub
        self.assertIsNone(database.get_club("OLD"))
        new_club = database.get_club("NEW")
        self.assertIsNotNone(new_club)
        self.assertEqual(new_club["name"], "Nowa Nazwa")

        # Sprawdź gracza
        p = database.get_player("Gracz Rebrand")
        self.assertEqual(p["club_tag"], "NEW")
        self.assertEqual(p["parent_club_tag"], "NEW")

        # Sprawdź historię transferów
        hist = database.get_player_transfer_history("Gracz Rebrand", 707)
        self.assertEqual(hist[0]["from_club"], "NEW")
        self.assertEqual(hist[0]["to_club"], "NEW")

    # ── Test Aneksu (extend_player_contract) ──
    def test_extend_player_contract_resets_flags(self):
        database.add_club("ANK", "Aneks Club", 1, 2)
        database.add_or_update_player("Gracz Aneks", 808, "ANK", "ANK", "5000", "TRANSFER", "2026-10-01 00:00:00")
        database.set_player_warning_flag("Gracz Aneks", "warned_7d")
        database.set_player_warning_flag("Gracz Aneks", "warned_3d")

        p_before = database.get_player("Gracz Aneks")
        self.assertEqual(p_before["warned_7d"], 1)

        # Przedłużenie umowy
        database.extend_player_contract("Gracz Aneks", "2028-06-30 23:59:59", "20000")
        p_after = database.get_player("Gracz Aneks")
        self.assertEqual(p_after["expires_at"], "2028-06-30 23:59:59")
        self.assertEqual(p_after["clause"], "20000")
        self.assertEqual(p_after["warned_7d"], 0)
        self.assertEqual(p_after["warned_3d"], 0)
        self.assertEqual(p_after["warned_1d"], 0)

    # ── Test Rozwiązania Kontraktu (terminate_player_contract) ──
    def test_terminate_player_contract(self):
        database.add_club("TRM", "Term Club", 1, 2)
        database.add_or_update_player("Gracz Zwolniony", 909, "TRM", "TRM", "Brak", "TRANSFER", "2027-01-01 00:00:00")
        self.assertEqual(1, database.get_club_player_count("TRM"))

        database.terminate_player_contract("Gracz Zwolniony")
        self.assertIsNone(database.get_player("Gracz Zwolniony"))
        self.assertEqual(0, database.get_club_player_count("TRM"))

    # ── Test Is Buyout i Reason w Applications ──
    def test_application_is_buyout_and_reason(self):
        app_id = database.create_application(
            app_type="TRANSFER", applicant_id=1,
            player_name="Wykupiony", target_club="AAA", source_club="BBB",
            amount="50000", is_buyout=True, reason="Aktywacja klauzuli odstępnego"
        )
        app = database.get_application(app_id)
        self.assertEqual(app["is_buyout"], 1)
        self.assertEqual(app["reason"], "Aktywacja klauzuli odstępnego")

    # ── Test Statystyk Ligi i Bazy Danych ──
    def test_league_and_db_stats(self):
        database.add_club("ST1", "Stat Club 1", 1, 2)
        database.add_or_update_player("G1", 1, "ST1", "ST1", "Brak", "TRANSFER", "2027-01-01 00:00:00")
        database.register_free_agent(2, "FA1")

        l_stats = database.get_league_stats()
        self.assertEqual(l_stats["clubs"], 1)
        self.assertEqual(l_stats["players"], 1)
        self.assertEqual(l_stats["free_agents"], 1)

        f_stats = database.get_db_file_stats()
        self.assertIn("clubs", f_stats)
        self.assertIn("journal_mode", f_stats)
        self.assertEqual(f_stats["clubs"], 1)

    # ── Test Backup Database Vacuum ──
    def test_backup_database_vacuum(self):
        database.add_club("BCK", "Backup Club", 1, 2)
        temp_fd, backup_file = tempfile.mkstemp(suffix=".db", prefix="test_backup_")
        os.close(temp_fd)
        os.remove(backup_file)

        try:
            database.backup_database_vacuum(backup_file)
            self.assertTrue(os.path.exists(backup_file))
            # Sprawdź czy to poprawna baza z naszym klubem
            conn = sqlite3.connect(backup_file)
            cur = conn.cursor()
            cur.execute("SELECT name FROM clubs WHERE tag = 'BCK'")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "Backup Club")
            conn.close()
        finally:
            if os.path.exists(backup_file):
                try:
                    os.remove(backup_file)
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
