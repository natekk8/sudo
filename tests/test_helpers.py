import unittest
from utils.helpers import (
    clean_tag, is_valid_tag, extract_ids, safe_thread_name,
    parse_expiry_date, parse_schedule_datetime, parse_amount, validate_amount_input,
    format_expiry_discord, format_schedule_discord, build_squad_bar
)

class TestHelpers(unittest.TestCase):
    def test_clean_tag(self):
        self.assertEqual(clean_tag(" fcb "), "FCB")

    def test_is_valid_tag_3chars(self):
        self.assertTrue(is_valid_tag("FCB"))
        self.assertTrue(is_valid_tag("fcb"))
        self.assertTrue(is_valid_tag("123"))

    def test_is_valid_tag_too_long(self):
        self.assertFalse(is_valid_tag("FCBA"))

    def test_extract_ids(self):
        self.assertEqual(extract_ids("<@123> <@!456>"), [123, 456])

    def test_extract_ids_none(self):
        self.assertEqual(extract_ids("No mentions here"), [])

    def test_safe_thread_name(self):
        long_name = "A" * 150
        self.assertEqual(len(safe_thread_name(long_name)), 100)

    def test_parse_expiry_days(self):
        self.assertIsNotNone(parse_expiry_date("5 dni"))
        self.assertIsNotNone(parse_expiry_date("14d"))

    def test_parse_expiry_date_dot_format(self):
        self.assertIsNotNone(parse_expiry_date("31.12.2030"))

    def test_parse_expiry_date_past_rejected(self):
        self.assertIsNone(parse_expiry_date("01.01.2000"))

    def test_parse_expiry_date_zero_rejected(self):
        self.assertIsNone(parse_expiry_date("0 dni"))

    def test_parse_schedule_relative_hours(self):
        self.assertIsNotNone(parse_schedule_datetime("2h"))

    def test_parse_schedule_relative_days(self):
        self.assertIsNotNone(parse_schedule_datetime("3d"))

    def test_parse_schedule_absolute_date_format(self):
        self.assertIsNotNone(parse_schedule_datetime("31.12.2030 18:00"))

    def test_parse_schedule_past_rejected(self):
        self.assertIsNone(parse_schedule_datetime("01.01.2000 18:00"))

    def test_validate_amount_brak(self):
        self.assertTrue(validate_amount_input("Brak"))

    def test_validate_amount_number(self):
        self.assertTrue(validate_amount_input("1000"))
        self.assertEqual(parse_amount("1,000"), 1000)

    def test_validate_amount_decimal_rejected(self):
        self.assertFalse(validate_amount_input("10.5"))

    def test_format_expiry_discord_format(self):
        self.assertIn("<t:", format_expiry_discord("2030-12-31 23:59:59"))

    def test_format_schedule_discord_format(self):
        self.assertIn("<t:", format_schedule_discord("2030-12-31 18:00:00"))

    def test_build_squad_bar_empty(self):
        self.assertEqual(build_squad_bar(0, 3), "`[□□□] 0/3` · 3 wolne miejsca")

    def test_build_squad_bar_partial(self):
        self.assertEqual(build_squad_bar(1, 3), "`[■□□] 1/3` · 2 wolne miejsca")

    def test_build_squad_bar_full(self):
        self.assertEqual(build_squad_bar(3, 3), "`[■■■] 3/3` · Kadra pełna ⛔")
