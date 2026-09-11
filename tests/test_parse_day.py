import unittest
from datetime import date
from unittest.mock import patch

import watch
from k_one import slots as slots_mod


def at(y, m, d):
    """把"今天"固定住，好测试跨年推断。"""
    return patch.object(
        slots_mod,
        "now_jst",
        lambda: slots_mod.datetime(y, m, d, 12, 0, tzinfo=slots_mod.JST),
    )


class TestParseDay(unittest.TestCase):
    def test_month_day_dash(self):
        with at(2026, 9, 12):
            self.assertEqual(watch.parse_day("10-03"), date(2026, 10, 3))

    def test_month_day_slash(self):
        with at(2026, 9, 12):
            self.assertEqual(watch.parse_day("10/3"), date(2026, 10, 3))

    def test_full_date(self):
        with at(2026, 9, 12):
            self.assertEqual(watch.parse_day("2026-10-03"), date(2026, 10, 3))

    def test_today_counts_as_this_year(self):
        with at(2026, 9, 12):
            self.assertEqual(watch.parse_day("9-12"), date(2026, 9, 12))

    def test_past_month_day_rolls_to_next_year(self):
        # 12 月问"1月5号"，指的是明年
        with at(2026, 12, 20):
            self.assertEqual(watch.parse_day("1-5"), date(2027, 1, 5))

    def test_whitespace_tolerated(self):
        with at(2026, 9, 12):
            self.assertEqual(watch.parse_day("  10-03 "), date(2026, 10, 3))

    def test_rejects_garbage(self):
        with at(2026, 9, 12):
            with self.assertRaises(ValueError):
                watch.parse_day("十月三号")

    def test_rejects_impossible_date(self):
        with at(2026, 9, 12):
            with self.assertRaises(ValueError):
                watch.parse_day("2-30")


class TestWeekdayJa(unittest.TestCase):
    def test_saturday(self):
        self.assertEqual(slots_mod.weekday_ja(date(2026, 10, 3)), "土")

    def test_monday(self):
        self.assertEqual(slots_mod.weekday_ja(date(2026, 10, 5)), "月")


if __name__ == "__main__":
    unittest.main()
