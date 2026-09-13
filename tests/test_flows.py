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

    def test_restore_application_upsert(self):
        app_data = {
            "id": 901,
            "type": "PODPISANIE",
            "applicant_id": 12345,
            "player_name": "TestRestored",
            "player_discord_id": 55555,
            "target_club": "FCB",
            "clause": "100k",
            "expires_at": "30.06.2027",
            "status": "PENDING"
        }
        res_id = database.restore_application(app_data)
        self.assertEqual(res_id, 901)
        app = database.get_application(901)
        self.assertIsNotNone(app)
        self.assertEqual(app["player_name"], "TestRestored")
        self.assertEqual(app["target_club"], "FCB")

    def test_reconstruct_app_from_message_podpisanie(self):
        import discord
        from unittest.mock import MagicMock
        from views.application_view import _reconstruct_app_from_message

        msg = MagicMock()
        msg.channel.id = 1234
        msg.id = 5678
        embed = discord.Embed(title="👤 PODPISANIE: Robert Lewandowski")
        embed.add_field(name="Zawodnik", value="<@4444> (Robert Lewandowski)")
        embed.add_field(name="Klub", value="`FCB`")
        embed.add_field(name="Wygasa", value="<t:1790000000:d> (20.09.2026)")
        embed.add_field(name="Klauzula", value="`250k`")
        msg.embeds = [embed]

        guild = MagicMock()
        guild.roles = []
        guild.get_member.return_value = None

        app = _reconstruct_app_from_message(msg, 902, guild)
        self.assertIsNotNone(app)
        self.assertEqual(app["id"], 902)
        self.assertEqual(app["type"], "PODPISANIE")
        self.assertEqual(app["player_name"], "Robert Lewandowski")
        self.assertEqual(app["player_discord_id"], 4444)
        self.assertEqual(app["target_club"], "FCB")
        self.assertEqual(app["clause"], "250k")
        self.assertEqual(app["expires_at"], "20.09.2026")

        saved = database.get_application(902)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["player_name"], "Robert Lewandowski")

    async def test_cb_fed_accept_with_reconstruction_fallback(self):
        import discord
        from unittest.mock import AsyncMock, MagicMock
        from views.application_view import ForumApplicationView
        from config import ROLE_FEDERACJA_ID

        # Wniosek 903 NIE istnieje w bazie SQLite
        self.assertIsNone(database.get_application(903))

        view = ForumApplicationView(903)
        interaction = MagicMock()
        fed_role = MagicMock()
        fed_role.id = ROLE_FEDERACJA_ID
        interaction.user.roles = [fed_role]
        interaction.user.mention = "<@111>"
        interaction.channel = MagicMock()
        interaction.channel.id = 555
        interaction.channel.edit = AsyncMock()
        interaction.client.get_channel.return_value.send = AsyncMock()
        interaction.client.fetch_user = AsyncMock()

        msg = MagicMock()
        msg.channel.id = 555
        msg.id = 8888
        embed = discord.Embed(title="👤 PODPISANIE: Odtworzony Gracz")
        embed.add_field(name="Zawodnik", value="<@7777> (Odtworzony Gracz)")
        embed.add_field(name="Klub", value="`FCB`")
        embed.add_field(name="Wygasa", value="30.06.2027")
        embed.add_field(name="Klauzula", value="`50k`")
        embed.add_field(name="Status", value="Oczekuje na akceptację...")
        msg.embeds = [embed]
        msg.edit = AsyncMock()

        interaction.message = msg
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        member = MagicMock()
        member.add_roles = AsyncMock()
        interaction.guild.get_member.return_value = member
        interaction.guild.get_role.return_value = MagicMock()

        await view.cb_fed_accept(interaction)

        # Sprawdź czy wniosek został pomyślnie zaakceptowany
        app = database.get_application(903)
        self.assertIsNotNone(app)
        self.assertEqual(app["status"], "ACCEPTED")
        p = database.get_player("Odtworzony Gracz")
        self.assertIsNotNone(p)
        self.assertEqual(p["club_tag"], "FCB")
        interaction.followup.send.assert_awaited()

    async def test_execute_accept_usuniecie_klubu(self):
        import discord
        from unittest.mock import AsyncMock, MagicMock
        from views.application_view import ForumApplicationView
        from config import ROLE_FEDERACJA_ID

        # Dodaj klub i gracza
        database.add_club("LIV", "Liverpool FC", 111, 222)
        database.add_or_update_player("Mo Salah", 9999, "LIV", None, "Brak", "Professional", "2026-12-31")
        self.assertIsNotNone(database.get_club("LIV"))
        self.assertIsNotNone(database.get_player("Mo Salah"))

        app_id = database.create_application(
            app_type="USUNIECIE_KLUBU", applicant_id=1234,
            club_name="Liverpool FC", club_tag="LIV", old_club_tag="LIV",
            reason="Likwidacja sekcji"
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
        interaction.client.fetch_user = AsyncMock()

        msg = MagicMock()
        embed = discord.Embed(title="🗑️ Wniosek o Usunięcie Klubu: LIV")
        embed.add_field(name="Klub", value="`LIV` – Liverpool FC")
        embed.add_field(name="Powód", value="Likwidacja sekcji")
        embed.add_field(name="Status", value="Oczekuje na decyzję...")
        msg.embeds = [embed]
        msg.edit = AsyncMock()

        interaction.message = msg
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        r_board = MagicMock()
        r_board.delete = AsyncMock()
        r_player = MagicMock()
        r_player.delete = AsyncMock()

        def get_role_mock(role_id):
            if role_id == 111: return r_board
            if role_id == 222: return r_player
            return None
        interaction.guild.get_role.side_effect = get_role_mock

        await view.cb_fed_accept(interaction)

        # Weryfikacja: klub i kontrakty graczy zostały usunięte
        self.assertIsNone(database.get_club("LIV"))
        self.assertIsNone(database.get_player("Mo Salah"))
        app = database.get_application(app_id)
        self.assertEqual(app["status"], "ACCEPTED")
        r_board.delete.assert_awaited()
        r_player.delete.assert_awaited()

    def test_federation_override_is_club_board_or_owner(self):
        from unittest.mock import MagicMock
        from utils.helpers import is_club_board_or_owner
        from config import ROLE_FEDERACJA_ID

        database.add_club("CHE", "Chelsea", 10, 20, founder_txt="<@555>", board_txt="<@666>")

        # Zwykły członek bez ról nie ma praw do CHE
        regular = MagicMock()
        regular.id = 999
        regular.roles = []
        regular.guild_permissions.administrator = False
        self.assertFalse(is_club_board_or_owner(regular, "CHE"))

        # Członek Zarządu Federacji MA pełne prawo do zarządzania dowolnym klubem
        fed_member = MagicMock()
        fed_member.id = 888
        fed_role = MagicMock()
        fed_role.id = ROLE_FEDERACJA_ID
        fed_member.roles = [fed_role]
        fed_member.guild_permissions.administrator = False
        self.assertTrue(is_club_board_or_owner(fed_member, "CHE"))

        # Administrator także ma pełne prawo
        admin_member = MagicMock()
        admin_member.id = 777
        admin_member.roles = []
        admin_member.guild_permissions.administrator = True
        self.assertTrue(is_club_board_or_owner(admin_member, "CHE"))

    def test_reconstruct_app_usuniecie_klubu(self):
        import discord
        from unittest.mock import MagicMock
        from views.application_view import _reconstruct_app_from_message

        msg = MagicMock()
        msg.id = 9999
        msg.channel.id = 555
        embed = discord.Embed(title="🗑️ USUNIĘCIE KLUBU: ARS – Arsenal")
        embed.add_field(name="Klub", value="`ARS`")
        embed.add_field(name="Powód", value="Brak aktywności")
        msg.embeds = [embed]

        app = _reconstruct_app_from_message(msg, 950, MagicMock())
        self.assertIsNotNone(app)
        self.assertEqual(app["type"], "USUNIECIE_KLUBU")
        self.assertEqual(app["club_tag"], "ARS")

    async def test_rejestracja_klubu_roles_only_to_founder_and_board_not_applicant(self):
        import discord
        from unittest.mock import AsyncMock, MagicMock
        from views.application_view import ForumApplicationView
        from config import ROLE_FEDERACJA_ID

        # applicant_id to np. Zarząd Federacji (999), który wypełnia wniosek za kogoś
        # Właściciel to 222, Zarząd to 333
        app_id = database.create_application(
            app_type="REJESTRACJA_KLUBU",
            applicant_id=999,
            club_name="Real Betis",
            club_tag="BET",
            founder_txt="<@222>",
            board_txt="<@333>"
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
        interaction.client.fetch_user = AsyncMock()

        msg = MagicMock()
        embed = discord.Embed(title="🏛️ Podsumowanie: Real Betis")
        embed.add_field(name="Skrót", value="`BET`")
        embed.add_field(name="Właściciel", value="<@222>")
        embed.add_field(name="Zarząd", value="<@333>")
        embed.add_field(name="Status", value="Oczekuje...")
        msg.embeds = [embed]
        msg.edit = AsyncMock()
        interaction.message = msg
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        r_zarzad = MagicMock()
        r_zarzad.id = 1001
        r_zawod = MagicMock()
        r_zawod.id = 1002

        interaction.guild.create_role = AsyncMock(side_effect=[r_zarzad, r_zawod])
        interaction.guild.get_role.return_value = None

        m_applicant = MagicMock()
        m_applicant.add_roles = AsyncMock()

        m_founder = MagicMock()
        m_founder.add_roles = AsyncMock()

        m_board = MagicMock()
        m_board.add_roles = AsyncMock()

        def get_member_mock(uid):
            if uid == 999: return m_applicant
            if uid == 222: return m_founder
            if uid == 333: return m_board
            return None
        interaction.guild.get_member.side_effect = get_member_mock

        await view.cb_fed_accept(interaction)

        # Weryfikacja: Właściciel (222) i Zarząd (333) dostali rolę r_zarzad
        m_founder.add_roles.assert_awaited_with(r_zarzad)
        m_board.add_roles.assert_awaited_with(r_zarzad)

        # Autor ticketa (999 - Federacja) NIE może otrzymać roli klubu
        m_applicant.add_roles.assert_not_awaited()

        # W bazie danych reprezentantem jest właściciel (222), a board_ids zawiera tylko [222, 333]
        club = database.get_club("BET")
        self.assertIsNotNone(club)
        self.assertEqual(club["reprezentant_dc"], 222)
        self.assertIn(222, club["board_ids"])
        self.assertIn(333, club["board_ids"])
        self.assertNotIn(999, club["board_ids"])
