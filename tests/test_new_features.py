import unittest
import os
import io
import csv
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import config
import database
import utils.league_config as league_config
from utils.helpers import send_audit_log, get_audit_channel
from cogs.admin import _generate_csv, _get_export_files, ResetConfirmView
from cogs.market import _build_club_info_embed, _build_all_clubs_embed
from views.application_view import ForumApplicationView

TEST_DB = "test_features_temp.db"


class TestNewFeatures(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        config.DB_PATH = TEST_DB
        database.core.DB_NAME = TEST_DB
        database.core.PERSISTENT_BACKUP_PATH = "test_features_backup.db"
        if os.path.exists(TEST_DB):
            try: os.remove(TEST_DB)
            except Exception: pass
        database.init_db()
        database.reset_contracts()
        database.reset_clubs()

    def tearDown(self):
        for f in (TEST_DB, "test_features_backup.db"):
            if os.path.exists(f):
                try: os.remove(f)
                except Exception: pass

    def test_expiring_or_overflow_players_filter(self):
        # 1. Gracz bez wygaśnięcia i bez overflow
        database.add_or_update_player(
            name="GraczStandard", discord_id=101, club_tag="LEG", parent_club_tag="LEG",
            clause="5000", contract_type="TRANSFER", expires_at=None, is_overflow=0
        )
        # 2. Gracz z wygasającym kontraktem
        database.add_or_update_player(
            name="GraczWygasajacy", discord_id=102, club_tag="LEG", parent_club_tag="LEG",
            clause="5000", contract_type="TRANSFER", expires_at="2026-12-31 23:59:59", is_overflow=0
        )
        # 3. Gracz overflow
        database.add_or_update_player(
            name="GraczOverflow", discord_id=103, club_tag="LEG", parent_club_tag="LEG",
            clause="5000", contract_type="TRANSFER", expires_at=None, is_overflow=1, slot_deadline="2026-10-10 12:00:00"
        )

        all_players = database.get_all_players()
        self.assertEqual(len(all_players), 3)

        filtered = database.get_expiring_or_overflow_players()
        self.assertEqual(len(filtered), 2)
        names = {p["name"] for p in filtered}
        self.assertIn("GraczWygasajacy", names)
        self.assertIn("GraczOverflow", names)
        self.assertNotIn("GraczStandard", names)

    def test_league_config_audit_channel(self):
        self.assertEqual(league_config.channel_audit_id(), 0)
        ok = league_config.set_config("cfg_channel_audit", "123456789012345678")
        self.assertTrue(ok)
        self.assertEqual(league_config.channel_audit_id(), 123456789012345678)

    async def test_send_audit_log_when_channel_configured(self):
        league_config.set_config("cfg_channel_audit", "999888777")
        mock_client = MagicMock()
        mock_channel = AsyncMock()
        mock_client.get_channel.return_value = mock_channel

        await send_audit_log(
            client=mock_client,
            guild=None,
            title="TEST AUDYT",
            description="Opis zdarzenia audytowego",
            color=0x2ecc71,
            fields=[("Pole 1", "Wartość 1", True)]
        )

        mock_channel.send.assert_awaited_once()
        sent_embed = mock_channel.send.await_args.kwargs.get("embed")
        self.assertIsNotNone(sent_embed)
        self.assertIn("TEST AUDYT", sent_embed.title)
        self.assertEqual(sent_embed.fields[0].name, "Pole 1")

    def test_csv_generator_and_exports(self):
        database.add_club("LEG", "Legia Warszawa", 111, 222, 333, "Jan", "Piotr", [111, 222])
        database.add_or_update_player("Kowalski", 555, "LEG", "LEG", "10000", "TRANSFER", "2026-11-01 12:00:00")
        database.add_to_transfer_list("Kowalski", "LEG", 15000, discord_id=555)
        database.add_transfer_history("Kowalski", 555, "WIS", "LEG", "TRANSFER", "12000")

        # Test pojedynczego generatora CSV
        sample_data = [{"name": "Kowalski", "club": "LEG"}]
        bio = _generate_csv(sample_data, ["name", "club"])
        content = bio.getvalue().decode('utf-8-sig')
        self.assertIn("name,club", content)
        self.assertIn("Kowalski,LEG", content)

        # Test _get_export_files
        all_files = _get_export_files("wszystko")
        self.assertEqual(len(all_files), 4)

        filenames = [f.filename for f in all_files]
        self.assertTrue(any("zawodnicy" in fn for fn in filenames))
        self.assertTrue(any("kluby" in fn for fn in filenames))
        self.assertTrue(any("historia" in fn for fn in filenames))
        self.assertTrue(any("lista_transferowa" in fn for fn in filenames))

    def test_club_info_embed_builder(self):
        database.add_club("LEG", "Legia Warszawa", 111, 222, 333, "<@111>", "<@222>", [111, 222])
        database.add_or_update_player("Kowalski", 555, "LEG", "LEG", "10000", "TRANSFER", "2026-11-01 12:00:00")
        database.add_to_transfer_list("Kowalski", "LEG", 15000, discord_id=555)

        embed = _build_club_info_embed("LEG")
        self.assertIsNotNone(embed)
        self.assertIn("Legia Warszawa [LEG]", embed.title)
        self.assertTrue(any("Kadra Zespołu" in f.name for f in embed.fields))
        self.assertTrue(any("Transferow" in f.name for f in embed.fields))

        # Test list all clubs
        all_embed = _build_all_clubs_embed()
        self.assertIsNotNone(all_embed)
        self.assertIn("Zarejestrowane Zespoły", all_embed.fields[0].name)
        self.assertIn("[LEG]", all_embed.fields[0].value)

    async def test_reset_confirm_view_flow(self):
        reset_called = False
        def fake_reset():
            nonlocal reset_called
            reset_called = True
            return "snapshot_test.db"

        view = ResetConfirmView(user_id=123, scope="kluby", reset_func=fake_reset, is_slash=True)
        self.assertEqual(view.scope, "kluby")
        btn = view.children[0]

        # Inny użytkownik nie może kliknąć
        mock_inter_other = MagicMock()
        mock_inter_other.user.id = 999
        mock_inter_other.response.send_message = AsyncMock()
        await btn.callback(mock_inter_other)
        self.assertFalse(reset_called)

        # Właściciel interakcji może kliknąć
        mock_inter_owner = MagicMock()
        mock_inter_owner.user.id = 123
        mock_inter_owner.client = MagicMock()
        mock_inter_owner.guild = MagicMock()
        mock_inter_owner.response.defer = AsyncMock()
        mock_inter_owner.edit_original_response = AsyncMock()

        with patch("utils.helpers.send_audit_log", new_callable=AsyncMock) as mock_audit:
            await btn.callback(mock_inter_owner)
            self.assertTrue(reset_called)
            mock_audit.assert_awaited_once()

    async def test_player_b_agree_in_exchange(self):
        # Tworzymy wniosek o wymianę z zakodowanym graczem B
        app_id = database.create_application(
            app_type="WYMIANA",
            applicant_id=100,
            player_name="GraczA",
            player_discord_id=200,
            target_club="KLA",
            source_club="KLB",
            new_founder_txt="WYMIANA|GraczB|300|5000|TRANSFER|2026-12-31|NONE",
            needs_player_agree=True
        )

        view = ForumApplicationView(app_id)
        mock_inter = MagicMock()
        mock_inter.user.id = 300  # Gracz B
        mock_inter.response.defer = AsyncMock()
        mock_inter.response.edit_message = AsyncMock()
        mock_inter.message = MagicMock()
        mock_inter.message.embeds = [MagicMock(fields=[MagicMock(name="Status", value="Status początkowy")])]
        mock_inter.message.edit = AsyncMock()
        mock_inter.followup.send = AsyncMock()

        await view.cb_player_b_agree(mock_inter)

        app_after = database.get_application(app_id)
        self.assertEqual(app_after.get("new_board_txt"), "AGREED")


if __name__ == '__main__':
    unittest.main()
