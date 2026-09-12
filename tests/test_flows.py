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

    def test_init_db_preserves_existing_data(self):
        database.add_or_update_player("Player 1", 100, "FCB", None, "Brak", "Professional", "2026-12-31")
        app_id = database.create_application("PODPISANIE", 999, player_name="NowyGracz", target_club="FCB")
        # Wywołanie init_db wielokrotnie nie może usuwać istniejących rekordów
        database.init_db()
        database.init_db()
        self.assertIsNotNone(database.get_player("Player 1"))
        self.assertIsNotNone(database.get_club("FCB"))
        self.assertIsNotNone(database.get_application(app_id))

    def test_reset_stuck_processing_applications(self):
        app_id = database.create_application("PODPISANIE", 999, player_name="StuckPlayer", target_club="FCB")
        # Symuluj przerwanie w trakcie zatwierdzania
        claimed = database.try_claim_application_for_approval(app_id)
        self.assertEqual(claimed["status"], "PENDING")
        self.assertEqual(database.get_application(app_id)["status"], "PROCESSING")
        # Reset przy starcie bota
        database.reset_stuck_processing_applications()
        self.assertEqual(database.get_application(app_id)["status"], "PENDING")

    def test_try_claim_can_reclaim_stuck_processing(self):
        app_id = database.create_application("PODPISANIE", 999, player_name="CrashPlayer", target_club="FCB")
        first_claim = database.try_claim_application_for_approval(app_id)
        self.assertIsNotNone(first_claim)
        # Równoległy claim w trakcie zwraca None (CAS ochrona przed podwójnym kliknięciem)
        self.assertIsNone(database.try_claim_application_for_approval(app_id))
        # Po cofnięciu zablokowanego statusu PROCESSING -> PENDING, ponowny claim działa
        database.revert_application_status(app_id, "PENDING")
        reclaimed = database.try_claim_application_for_approval(app_id)
        self.assertIsNotNone(reclaimed)
        # Zamknięty wniosek nie może być re-claimowany
        database.set_application_status(app_id, "ACCEPTED")
        self.assertIsNone(database.try_claim_application_for_approval(app_id))

    def test_forum_view_player_without_discord_no_agree_button(self):
        from views.application_view import ForumApplicationView
        app_id = database.create_application(
            app_type="PODPISANIE", applicant_id=999,
            player_name="BezDiscorda", player_discord_id=None,
            target_club="FCB", needs_player_agree=True
        )
        view = ForumApplicationView(app_id)
        custom_ids = [item.custom_id for item in view.children if hasattr(item, "custom_id")]
        # Przycisk podpisu gracza NIE powinien się pojawić
        self.assertNotIn(f"app:{app_id}:p_agree", custom_ids)
        # Przycisk Federacji POWINIEN być obecny
        self.assertIn(f"app:{app_id}:fed_accept", custom_ids)
        self.assertIn(f"app:{app_id}:fed_reject", custom_ids)

    def test_forum_view_update_status_field_without_discord(self):
        import discord
        from views.application_view import ForumApplicationView
        app_id = database.create_application(
            app_type="PODPISANIE", applicant_id=999,
            player_name="BezDiscorda", player_discord_id=None,
            target_club="FCB", needs_player_agree=True
        )
        view = ForumApplicationView(app_id)
        embed = discord.Embed(title="Wniosek")
        embed.add_field(name="Status", value="Stary status")
        app = database.get_application(app_id)
        updated = view._update_status_field(embed, app)
        self.assertIn("• Zawodnik: ℹ️ Brak konta Discord", updated.fields[0].value)


class TestAsyncApplicationView(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import config
        config.DB_PATH = TEST_DB
        if os.path.exists(TEST_DB): os.remove(TEST_DB)
        database.init_db()
        database.add_club("FCB", "FC Barcelona", 1, 2)

    async def asyncTearDown(self):
        if os.path.exists(TEST_DB): os.remove(TEST_DB)

    async def test_execute_accept_player_without_discord_success(self):
        from views.application_view import ForumApplicationView
        from unittest.mock import AsyncMock, MagicMock
        import discord

        app_id = database.create_application(
            app_type="PODPISANIE", applicant_id=999,
            player_name="JanKowalski", player_discord_id=None,
            target_club="FCB", clause="500", expires_at="2027-06-30"
        )
        view = ForumApplicationView(app_id)

        # Mock interaction
        interaction = MagicMock()
        interaction.user.mention = "<@111>"
        interaction.channel = MagicMock()
        embed = discord.Embed(title="Wniosek")
        embed.add_field(name="Status", value="Oczekuje")
        interaction.message.embeds = [embed]
        interaction.message.edit = AsyncMock()
        guild = MagicMock()
        guild.get_role.return_value = None

        app = database.try_claim_application_for_approval(app_id)
        ok = await view._execute_accept(interaction, app, "PODPISANIE", guild, kom_channel=None)

        self.assertTrue(ok)
        saved = database.get_player("JanKowalski")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["club_tag"], "FCB")
        self.assertIsNone(saved["discord_id"])
        self.assertEqual(database.get_application(app_id)["status"], "ACCEPTED")

    async def test_fed_reject_direct_without_modal(self):
        from views.application_view import ForumApplicationView
        from config import ROLE_FEDERACJA_ID
        from unittest.mock import AsyncMock, MagicMock
        import discord

        app_id = database.create_application(
            app_type="PODPISANIE", applicant_id=999,
            player_name="DoOdrzucenia", player_discord_id=None,
            target_club="FCB"
        )
        view = ForumApplicationView(app_id)

        interaction = MagicMock()
        fed_role = MagicMock()
        fed_role.id = ROLE_FEDERACJA_ID
        interaction.user.roles = [fed_role]
        interaction.user.mention = "<@111>"
        interaction.channel = MagicMock()
        interaction.channel.edit = AsyncMock()
        interaction.client.get_channel.return_value.send = AsyncMock()
        embed = discord.Embed(title="Wniosek")
        embed.add_field(name="Status", value="Oczekuje")
        interaction.message.embeds = [embed]
        interaction.message.edit = AsyncMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await view.cb_fed_reject(interaction)

        app = database.get_application(app_id)
        self.assertEqual(app["status"], "REJECTED")
        self.assertIn("Federacja", app["rejected_by"])
        interaction.followup.send.assert_awaited()

    async def test_on_interaction_fallback_for_unregistered_view(self):
        from main import on_interaction
        from config import ROLE_FEDERACJA_ID
        from unittest.mock import AsyncMock, MagicMock
        import discord

        app_id = database.create_application(
            app_type="PODPISANIE", applicant_id=999,
            player_name="FallbackPlayer", player_discord_id=None,
            target_club="FCB"
        )

        interaction = MagicMock()
        interaction.type = discord.InteractionType.component
        interaction.data = {"custom_id": f"app:{app_id}:fed_accept"}
        interaction.response.is_done.return_value = False
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        fed_role = MagicMock()
        fed_role.id = ROLE_FEDERACJA_ID
        interaction.user.roles = [fed_role]
        interaction.user.mention = "<@111>"
        interaction.channel = MagicMock()
        interaction.channel.id = 555
        interaction.channel.edit = AsyncMock()
        interaction.client.get_channel.return_value.send = AsyncMock()
        interaction.message = MagicMock()
        interaction.message.id = 777
        embed = discord.Embed(title="Wniosek")
        embed.add_field(name="Status", value="Oczekuje")
        interaction.message.embeds = [embed]
        interaction.message.edit = AsyncMock()

        await on_interaction(interaction)

        app = database.get_application(app_id)
        self.assertEqual(app["status"], "ACCEPTED")
        saved = database.get_player("FallbackPlayer")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["club_tag"], "FCB")
