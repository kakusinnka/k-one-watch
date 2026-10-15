import json
import unittest
from datetime import date, datetime
from pathlib import Path

from k_one import slots as m
from k_one.slots import JST, Slot

FIXTURE = Path(__file__).parent / "fixtures" / "week_cut.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def slot(stamp: str, mark: str = m.MARK_OPEN, menu_id: str = "M1") -> Slot:
    return Slot(
        start=datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=JST),
        menu_id=menu_id,
        menu_name="カット",
        mark=mark,
    )


class TestParse(unittest.TestCase):
    """fixture 是 2026/09/21-27 カット 的真实响应快照。"""

    def setUp(self):
        self.parsed = m.parse(load_fixture())

    def test_extracts_exactly_the_active_slots(self):
        self.assertEqual(len(self.parsed), 17)
        self.assertEqual(
            [s.start.strftime("%Y%m%d%H") for s in self.parsed],
            [
                "2026092315", "2026092316",
                "2026092410", "2026092411", "2026092412", "2026092413",
                "2026092416", "2026092417",
                "2026092510", "2026092512", "2026092513",
                "2026092515", "2026092516", "2026092517",
                "2026092712", "2026092713", "2026092715",
            ],
        )

    def test_carries_menu_identity(self):
        self.assertTrue(all(s.menu_id == "s0000A5844" for s in self.parsed))
        self.assertTrue(all(s.menu_name == "カット" for s in self.parsed))

    def test_slots_are_jst(self):
        self.assertEqual(self.parsed[0].start.utcoffset().total_seconds(), 9 * 3600)

    def test_closed_mondays_and_tuesdays_produce_nothing(self):
        # 9/21(月) 9/22(火) 定休，不该有任何空位
        self.assertFalse([s for s in self.parsed if s.start.day in (21, 22)])

    def test_result_is_sorted(self):
        self.assertEqual(self.parsed, sorted(self.parsed))


class TestSlot(unittest.TestCase):
    def test_key_is_stable_and_hour_granular(self):
        self.assertEqual(slot("20260927150000").key, "M1@2026092715")

    def test_label_uses_japanese_weekday(self):
        self.assertEqual(slot("20260927150000").label(), "9/27(日) 15:00")

    def test_few_left_flag(self):
        self.assertFalse(slot("20260927150000").few_left)
        self.assertTrue(slot("20260927150000", m.MARK_FEW_LEFT).few_left)


class TestWeekdayMask(unittest.TestCase):
    def test_weekend(self):
        self.assertEqual(m.weekday_mask(["sat", "sun"]), {5, 6})

    def test_empty_means_no_restriction(self):
        self.assertIsNone(m.weekday_mask([]))

    def test_case_and_whitespace_tolerant(self):
        self.assertEqual(m.weekday_mask([" Sat ", "SUNDAY"]), {5, 6})

    def test_rejects_typo(self):
        with self.assertRaises(ValueError) as ctx:
            m.weekday_mask(["satrday"])
        self.assertIn("satrday", str(ctx.exception))


class _Rule:
    """测试用的轻量规则，字段与 config.Rule 一致。"""

    def __init__(self, weekdays=(), hour_from=10, hour_to=18):
        self.weekdays = list(weekdays)
        self.hour_from = hour_from
        self.hour_to = hour_to


WEEKEND = _Rule(weekdays=["sat", "sun"], hour_from=10, hour_to=18)
AFTER_WORK = _Rule(weekdays=[], hour_from=17, hour_to=18)
ANYTIME = _Rule(weekdays=[], hour_from=10, hour_to=18)


class TestMatches(unittest.TestCase):
    def test_weekday_restriction(self):
        sunday = slot("20260927120000")
        self.assertTrue(m.matches(sunday, weekdays=["sun"], hour_from=10, hour_to=18))
        self.assertFalse(m.matches(sunday, weekdays=["sat"], hour_from=10, hour_to=18))

    def test_empty_weekdays_means_any_day(self):
        friday = slot("20260925170000")
        self.assertTrue(m.matches(friday, weekdays=[], hour_from=17, hour_to=18))

    def test_hour_window_is_half_open(self):
        self.assertTrue(
            m.matches(slot("20260925170000"), weekdays=[], hour_from=17, hour_to=18)
        )
        self.assertFalse(
            m.matches(slot("20260925180000"), weekdays=[], hour_from=17, hour_to=18)
        )


class TestApplyFilters(unittest.TestCase):
    def setUp(self):
        self.parsed = m.parse(load_fixture())
        self.base = dict(
            include_few_left=True,
            date_from=date(2026, 9, 13),
            date_to=date(2026, 10, 11),
        )

    def test_weekend_rule_keeps_only_sunday_slots(self):
        # fixture 那周 9/26(土) 全满，只剩 9/27(日) 的 12/13/15 点
        kept = m.apply_filters(self.parsed, rules=[WEEKEND], **self.base)
        self.assertEqual(
            [s.start.strftime("%m%d%H") for s in kept], ["092712", "092713", "092715"]
        )

    def test_unrestricted_rule_keeps_all(self):
        kept = m.apply_filters(self.parsed, rules=[ANYTIME], **self.base)
        self.assertEqual(len(kept), 17)

    def test_rules_are_ored_together(self):
        """周末全天 + 每天 17:00 —— 单一时间段表达不了这个组合。"""
        kept = m.apply_filters(self.parsed, rules=[WEEKEND, AFTER_WORK], **self.base)
        stamps = [s.start.strftime("%m%d%H") for s in kept]
        self.assertIn("092712", stamps)   # 周日白天，命中「周末全天」
        self.assertIn("092417", stamps)   # 周四 17 点，命中「下班后」
        self.assertIn("092517", stamps)   # 周五 17 点，命中「下班后」
        self.assertNotIn("092410", stamps)  # 周四 10 点，两条都不命中

    def test_no_duplicates_when_both_rules_match(self):
        # 周日 17:00 同时命中两条规则，不能推两遍
        both = [slot("20260927170000")]
        kept = m.apply_filters(both, rules=[WEEKEND, AFTER_WORK], **self.base)
        self.assertEqual(len(kept), 1)

    def test_result_keeps_chronological_order(self):
        kept = m.apply_filters(self.parsed, rules=[WEEKEND, AFTER_WORK], **self.base)
        self.assertEqual(kept, sorted(kept))

    def test_date_range_is_inclusive_on_both_ends(self):
        only_27 = m.apply_filters(
            self.parsed,
            rules=[ANYTIME],
            include_few_left=True,
            date_from=date(2026, 9, 27),
            date_to=date(2026, 9, 27),
        )
        self.assertEqual(len(only_27), 3)

    def test_date_range_excludes_outside(self):
        self.assertEqual(
            m.apply_filters(
                self.parsed,
                rules=[ANYTIME],
                include_few_left=True,
                date_from=date(2026, 10, 1),
                date_to=date(2026, 10, 5),
            ),
            [],
        )

    def test_can_drop_few_left(self):
        mixed = [slot("20260927120000"), slot("20260927130000", m.MARK_FEW_LEFT)]
        kept = m.apply_filters(
            mixed,
            rules=[WEEKEND],
            include_few_left=False,
            date_from=date(2026, 9, 13),
            date_to=date(2026, 10, 11),
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].start.hour, 12)


class TestMergeRuns(unittest.TestCase):
    def test_merges_consecutive_hours_into_one_span(self):
        got = m.merge_runs([slot("20260927120000"), slot("20260927130000")])
        self.assertEqual(got, ["9/27(日) 12:00-14:00"])

    def test_splits_on_gap(self):
        got = m.merge_runs(
            [slot("20260927120000"), slot("20260927130000"), slot("20260927150000")]
        )
        self.assertEqual(got, ["9/27(日) 12:00-14:00 / 15:00-16:00"])

    def test_one_line_per_day(self):
        got = m.merge_runs([slot("20260926100000"), slot("20260927150000")])
        self.assertEqual(got, ["9/26(土) 10:00-11:00", "9/27(日) 15:00-16:00"])

    def test_marks_few_left_span(self):
        got = m.merge_runs([slot("20260927120000", m.MARK_FEW_LEFT)])
        self.assertEqual(got, ["9/27(日) 12:00-13:00(残りわずか)"])

    def test_unsorted_input_still_merges(self):
        got = m.merge_runs([slot("20260927130000"), slot("20260927120000")])
        self.assertEqual(got, ["9/27(日) 12:00-14:00"])

    def test_empty(self):
        self.assertEqual(m.merge_runs([]), [])


if __name__ == "__main__":
    unittest.main()
