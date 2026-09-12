import unittest, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
TEST_DB = 'test_liga_temp.db'
import database

class TestFlows(unittest.TestCase):
    def setUp(self):
        import config
        config.DB_PATH = TEST_DB
        if os.path.exists(TEST_DB): os.remove(TEST_DB)
        database.init_db()
        database.add_club("FCB", "FC Barcelona", 1, 2)
        database.add_club("RMA", "Real Madrid", 3, 4)
    def tearDown(self):
        if os.path.exists(TEST_DB): os.remove(TEST_DB)

    def test_is_player_under_contract_finds_by_name(self):
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        self.assertIsNotNone(database.is_player_under_contract("Player 1"))

    def test_is_player_under_contract_finds_by_discord_id(self):
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        self.assertIsNotNone(database.is_player_under_contract(None, 100))

    def test_is_player_under_contract_returns_none_if_free(self):
        self.assertIsNone(database.is_player_under_contract("Free Player"))

    def test_contract_theft_prevention_blocks_resign(self):
        # A player under contract shouldn't be signable without transfer
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        p = database.is_player_under_contract("Player 1")
        self.assertEqual(p["club_tag"], "FCB")

    def test_club_player_count_limit(self):
        for i in range(3):
            database.add_or_update_player(f"Player {i}", 100+i, "FCB", None, "Brak", "Professional", "2026-12-31")
        self.assertEqual(database.get_club_player_count("FCB"), 3)

    def test_duplicate_discord_id_prevention(self):
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        database.add_or_update_player("Player 2", 100, "RMA", None, "Brak", "Professional", "2026-12-31")
        self.assertIsNone(database.get_player("Player 1"))
        self.assertIsNotNone(database.get_player("Player 2"))

    def test_case_insensitive_player_lookup(self):
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        self.assertIsNotNone(database.get_player("player 1"))

    def test_extend_contract_resets_flags(self):
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        database.set_player_warning_flag("Player 1", "warned_7d")
        database.extend_player_contract("Player 1", "2027-12-31", "Nowa")
        p = database.get_player("Player 1")
        self.assertEqual(p["warned_7d"], 0)
        self.assertEqual(p["expires_at"], "2027-12-31")

    def test_terminate_contract_by_discord_id(self):
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        database.terminate_player_contract(None, 100)
        self.assertIsNone(database.get_player("Player 1"))

    def test_loan_return_restores_original_contract(self):
        database.add_or_update_player("Player 1", 100, "FCB", "RMA", "Brak", "Loan", "2026-12-31", "2027-12-31", "Brak")
        # Wypożyczenie
        p = database.get_player("Player 1")
        self.assertEqual(p["parent_club_tag"], "RMA")

    def test_rebrand_cascade_updates_players(self):
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        database.rebrand_club("FCB", "BAR", "Barcelona")
        p = database.get_player("Player 1")
        self.assertEqual(p["club_tag"], "BAR")

    def test_rebrand_cascade_updates_history(self):
        database.add_transfer_history("Player 1", 100, "FCB", "RMA", "TRANSFER", "100")
        database.rebrand_club("FCB", "BAR", "Barcelona")
        hist = database.get_player_transfer_history("Player 1")
        self.assertEqual(hist[0]["from_club"], "BAR")
