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

    async def test_create_ticket_channel_permissions(self):
        from services.flows.shared import _create_ticket_channel
        guild = MagicMock()
        guild.default_role = MagicMock()
        guild.me = MagicMock()
        user = MagicMock()
        user.mention = "<@123>"
        guild.get_role.return_value = None
        guild.categories = []
        guild.create_category = AsyncMock(return_value=None)
        created_channel = AsyncMock()
        guild.create_text_channel = AsyncMock(return_value=created_channel)

        chan = await _create_ticket_channel(guild, user, "test")
        guild.create_text_channel.assert_awaited_once()
        _, kwargs = guild.create_text_channel.await_args
        overwrites = kwargs["overwrites"]

        # @everyone musi mieć view_channel=True, ale send_messages=False
        def_ov = overwrites[guild.default_role]
        self.assertTrue(def_ov.view_channel)
        self.assertFalse(def_ov.send_messages)

        # Użytkownik i bot muszą mieć view_channel=True i send_messages=True
        self.assertTrue(overwrites[user].view_channel)
        self.assertTrue(overwrites[user].send_messages)
        self.assertTrue(overwrites[guild.me].view_channel)
        self.assertTrue(overwrites[guild.me].send_messages)

    def test_extract_ids_handles_mentions_and_numeric_ids(self):
        from utils.helpers import extract_ids
        txt1 = "Właściciel: <@111222333444555666> oraz <@!999888777666555444>"
        self.assertEqual(extract_ids(txt1), [111222333444555666, 999888777666555444])

        txt2 = "Zarząd: 111222333444555666 i tekst 999888777666555444"
        self.assertEqual(extract_ids(txt2), [111222333444555666, 999888777666555444])

        txt3 = "Brak osób, same słowa i mała liczba 12345"
        self.assertEqual(extract_ids(txt3), [])

    def test_update_club_full_clearing_board_and_rep(self):
        database.add_club("LEG", "Legia Warszawa", role_board_id=222, role_player_id=333,
                          reprezentant_dc=111, founder_txt="Jan", board_txt="Piotr", board_ids=[111, 222])
        c1 = database.get_club("LEG")
        self.assertEqual(c1["reprezentant_dc"], 111)
        self.assertEqual(c1["board_ids"], [111, 222])

        # Wyczyszczenie do pustego zarządu i braku reprezentanta
        ok = database.update_club_full("LEG", new_board_ids=[], new_rep_id=None)
        self.assertTrue(ok)

        c2 = database.get_club("LEG")
        self.assertIsNone(c2["reprezentant_dc"])
        self.assertEqual(c2["board_ids"], [])

    async def test_update_club_board_data_command_flow(self):
        from cogs.market import _update_club_board_data
        database.add_club("WIS", "Wisła Kraków", role_board_id=202, role_player_id=303,
                          reprezentant_dc=101, founder_txt="Oryginalny", board_txt="StaryZarzad", board_ids=[101, 202])
        database.add_or_update_player("Kapitan", 999, "WIS", "WIS", "5000", "TRANSFER", expires_at=None)

        # 1. Podgląd zarządu bez argumentów
        mock_admin = MagicMock()
        mock_admin.id = 777
        mock_admin.guild_permissions.administrator = True
        mock_guild = MagicMock()
        mock_guild.get_role.return_value = None
        mock_guild.get_channel.return_value = None

        ok, msg, embed = await _update_club_board_data(mock_guild, mock_admin, "WIS", None, None)
        self.assertTrue(ok)
        self.assertIsNotNone(embed)
        self.assertIn("Władze Klubu: Wisła Kraków", embed.title)

        # 2. Zmiana właściciela i zarządu na nowe osoby
        ok, msg, embed = await _update_club_board_data(mock_guild, mock_admin, "WIS", "<@555666777888999000>", "999888777666555444")
        self.assertTrue(ok)
        c_mod = database.get_club("WIS")
        self.assertEqual(c_mod["reprezentant_dc"], 555666777888999000)
        self.assertIn(555666777888999000, c_mod["board_ids"])
        self.assertIn(999888777666555444, c_mod["board_ids"])

        # 3. Wyczyszczenie zarządu i reprezentanta słowem "brak"
        ok, msg, embed = await _update_club_board_data(mock_guild, mock_admin, "WIS", "brak", "usun")
        self.assertTrue(ok)
        c_cleared = database.get_club("WIS")
        self.assertIsNone(c_cleared["reprezentant_dc"])
        self.assertEqual(c_cleared["board_ids"], [])

        # 4. Sprawdzenie, czy kontrakt i gracz nie zostały w żaden sposób naruszone
        player = database.get_player_by_discord_id(999)
        self.assertIsNotNone(player)
        self.assertEqual(player["club_tag"], "WIS")


if __name__ == '__main__':
    unittest.main()
