import unittest, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
TEST_DB = 'test_liga_temp.db'
import database

class TestDatabase(unittest.TestCase):
    def setUp(self):
        import config
        config.DB_PATH = TEST_DB
        if os.path.exists(TEST_DB): os.remove(TEST_DB)
        database.init_db()
    def tearDown(self):
        if os.path.exists(TEST_DB): os.remove(TEST_DB)

    def test_add_and_get_club(self):
        database.add_club("FCB", "FC Barcelona", 1, 2)
        c = database.get_club("fcb")
        self.assertEqual(c["name"], "FC Barcelona")
        self.assertEqual(c["tag"], "FCB")

    def test_club_case_insensitive(self):
        database.add_club("RMA", "Real", 1, 2)
        self.assertIsNotNone(database.get_club("rma"))
        self.assertIsNotNone(database.get_club("Rma"))

    def test_club_update_cascade(self):
        database.add_club("OLD", "Old Name", 1, 2)
        database.add_or_update_player("Player 1", 100, "OLD", None, "Brak", "Professional", "2026-12-31")
        database.update_club_full("OLD", new_tag="NEW", new_name="New Name")
        self.assertIsNone(database.get_club("OLD"))
        self.assertEqual(database.get_club("NEW")["name"], "New Name")
        p = database.get_player("Player 1")
        self.assertEqual(p["club_tag"], "NEW")

    def test_add_player(self):
        database.add_club("FCB", "FC Barcelona", 1, 2)
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        p = database.get_player("Player 1")
        self.assertEqual(p["discord_id"], 100)

    def test_player_contract_limit_3(self):
        database.add_club("FCB", "FC Barcelona", 1, 2)
        for i in range(3):
            database.add_or_update_player(f"Player {i}", 100+i, "FCB", None, "Brak", "Professional", "2026-12-31")
        self.assertEqual(database.get_club_player_count("FCB"), 3)

    def test_terminate_contract(self):
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        database.terminate_player_contract("Player 1")
        self.assertIsNone(database.get_player("Player 1"))

    def test_free_agent_register_remove(self):
        database.register_free_agent(123, "FA 1")
        self.assertTrue(database.is_free_agent(123))
        database.remove_free_agent(123)
        self.assertFalse(database.is_free_agent(123))

    def test_free_agents_pagination(self):
        for i in range(30):
            database.register_free_agent(100+i, f"FA {i}")
        agents, total = database.get_free_agents_paginated(limit=10)
        self.assertEqual(len(agents), 10)
        self.assertEqual(total, 30)

    def test_application_lifecycle(self):
        app_id = database.create_application("PODPISANIE", 123)
        app = database.get_application(app_id)
        self.assertEqual(app["status"], "PENDING")
        claimed = database.try_claim_application_for_approval(app_id)
        self.assertIsNotNone(claimed)
        self.assertEqual(database.get_application(app_id)["status"], "PROCESSING")
        database.set_application_status(app_id, "ACCEPTED")
        self.assertEqual(database.get_application(app_id)["status"], "ACCEPTED")

    def test_transfer_history(self):
        database.add_transfer_history("Player 1", 123, "FCB", "RMA", "TRANSFER", "100M")
        hist = database.get_player_transfer_history("Player 1")
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["to_club"], "RMA")

    def test_market_status(self):
        database.set_market_status("CLOSED")
        self.assertFalse(database.is_market_open())
        database.set_market_status("OPEN")
        self.assertTrue(database.is_market_open())

    def test_settings_crud(self):
        database.set_setting("key1", "val1")
        self.assertEqual(database.get_setting("key1"), "val1")
        database.delete_setting("key1")
        self.assertIsNone(database.get_setting("key1"))

    def test_ticket_counter_increment(self):
        database.reset_database_for_new_season()
        self.assertEqual(database.get_next_ticket_id(), "001")
        self.assertEqual(database.get_next_ticket_id(), "002")

    def test_reset_season_full(self):
        database.add_club("FCB", "FC Barcelona", 1, 2)
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        database.reset_database_for_new_season()
        self.assertIsNone(database.get_club("FCB"))
        self.assertIsNone(database.get_player("Player 1"))
        self.assertTrue(database.is_market_open())
        self.assertEqual(database.get_setting("season_initialized"), "2026_27")

    def test_reset_season_preserves_setup_config(self):
        # Symulacja ustawień z panelu /setup
        database.set_setting("cfg_max_players", "5")
        database.set_setting("cfg_channel_forum", "123456789")
        database.set_setting("cfg_channel_komunikaty", "987654321")
        database.set_setting("cfg_role_federacja", "111222333")
        database.set_setting("cfg_season_label", "2026/27")
        database.set_setting("cfg_league_name", "Federacja Siatkówki Stołowej (FSS)")

        # Dodaj dane sezonowe
        database.add_club("FCB", "FC Barcelona", 1, 2)
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        database.register_free_agent(555, "FreeAgent")
        database.create_application("PODPISANIE", 100)
        database.add_transfer_history("Player 1", 100, "FCB", "RMA", "TRANSFER", "5000")

        # Wykonaj reset sezonu
        database.reset_database_for_new_season()

        # Weryfikacja: ustawienia /setup MUSZĄ pozostać nienaruszone
        self.assertEqual(database.get_setting("cfg_max_players"), "5")
        self.assertEqual(database.get_setting("cfg_channel_forum"), "123456789")
        self.assertEqual(database.get_setting("cfg_channel_komunikaty"), "987654321")
        self.assertEqual(database.get_setting("cfg_role_federacja"), "111222333")
        self.assertEqual(database.get_setting("cfg_season_label"), "2026/27")
        self.assertEqual(database.get_setting("cfg_league_name"), "Federacja Siatkówki Stołowej (FSS)")

        # Weryfikacja: dane ligowe zostały wyczyszczone
        self.assertIsNone(database.get_club("FCB"))
        self.assertIsNone(database.get_player("Player 1"))
        self.assertFalse(database.is_free_agent(555))
        self.assertEqual(len(database.get_pending_applications()), 0)
        self.assertEqual(len(database.get_player_transfer_history("Player 1")), 0)

        # Weryfikacja: licznik ticketów zresetowany do 001
        self.assertEqual(database.get_next_ticket_id(), "001")
        self.assertTrue(database.is_market_open())

    def test_delete_club(self):
        database.add_club("DEL", "Delete Club", 10, 20)
        database.add_or_update_player("Player Del", 999, "DEL", None, "Brak", "Professional", "2026-12-31")
        self.assertIsNotNone(database.get_club("DEL"))
        self.assertIsNotNone(database.get_player("Player Del"))

        deleted = database.delete_club("DEL", terminate_players=True)
        self.assertTrue(deleted)
        self.assertIsNone(database.get_club("DEL"))
        self.assertIsNone(database.get_player("Player Del"))

        # Ponowne usunięcie powinno zwrócić False
        self.assertFalse(database.delete_club("DEL"))

    def test_reset_all_full_clears_setup(self):
        database.set_setting("cfg_max_players", "7")
        database.add_club("FCB", "Barcelona", 1, 2)
        database.reset_all(full_reset_including_setup=True)
        self.assertIsNone(database.get_setting("cfg_max_players"))
        self.assertIsNone(database.get_club("FCB"))
        self.assertTrue(database.is_market_open())

    def test_reset_clubs_preserves_free_agents(self):
        database.add_club("KLU", "Klub", 1, 2)
        database.add_or_update_player("Player 1", 101, "KLU", None, "Brak", "Professional", "2026-12-31")
        database.register_free_agent(202, "FreeAgent")
        database.set_setting("cfg_max_players", "4")

        database.reset_clubs()

        self.assertIsNone(database.get_club("KLU"))
        self.assertIsNone(database.get_player("Player 1"))
        self.assertTrue(database.is_free_agent(202))
        self.assertEqual(database.get_setting("cfg_max_players"), "4")

    def test_reset_contracts_preserves_clubs(self):
        database.add_club("KLU", "Klub", 1, 2)
        database.add_or_update_player("Player 1", 101, "KLU", None, "Brak", "Professional", "2026-12-31")
        database.register_free_agent(202, "FreeAgent")

        database.reset_contracts()

        self.assertIsNotNone(database.get_club("KLU"))
        self.assertIsNone(database.get_player("Player 1"))
        self.assertFalse(database.is_free_agent(202))

    def test_reset_applications_only(self):
        database.add_club("KLU", "Klub", 1, 2)
        app_id = database.create_application("PODPISANIE", 101)
        database.set_application_message(app_id, 100, 200)
        self.assertEqual(len(database.get_pending_applications()), 1)

        database.reset_applications()

        self.assertEqual(len(database.get_pending_applications()), 0)
        self.assertIsNone(database.get_application(app_id))
        self.assertIsNotNone(database.get_club("KLU"))
        self.assertEqual(database.get_next_ticket_id(), "001")

    def test_reset_market_only(self):
        database.register_free_agent(202, "FreeAgent")
        database.set_setting("market_status", "CLOSED")
        database.set_setting("market_close_at", "2026-12-31 18:00:00")

        database.reset_market()

        self.assertFalse(database.is_free_agent(202))
        self.assertTrue(database.is_market_open())
        self.assertIsNone(database.get_setting("market_close_at"))

    def test_reset_setup_only(self):
        database.set_setting("cfg_max_players", "8")
        database.add_club("KLU", "Klub", 1, 2)

        database.reset_setup()

        self.assertIsNone(database.get_setting("cfg_max_players"))
        self.assertIsNotNone(database.get_club("KLU"))


