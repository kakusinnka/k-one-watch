"""watch.py 里纯函数的测试。

加 --date 时一处替换误伤了 _filtered（引用了不存在的 until），check 和
不带 --date 的 show 全都 NameError —— 当时没有任何测试覆盖这两条路径。
"""

import unittest
from datetime import date
from unittest.mock import patch

import watch
from k_one import config
from k_one import slots as slots_mod
from k_one.slots import JST, MARK_FEW_LEFT, Slot


def at(y, m, d):
    return patch.object(
        slots_mod,
        "now_jst",
        lambda: slots_mod.datetime(y, m, d, 12, 0, tzinfo=JST),
    )


def slot(stamp: str, mark: str = slots_mod.MARK_OPEN) -> Slot:
    return Slot(
        start=slots_mod.datetime.strptime(stamp, "%Y%m%d%H").replace(tzinfo=JST),
        menu_id="s0000A5844",
        menu_name="カット",
        mark=mark,
    )


def cfg(**overrides) -> config.Config:
    c = config.Config()
    for k, v in overrides.items():
        setattr(c.watch, k, v)
    return c


class TestHorizon(unittest.TestCase):
    def test_starts_tomorrow(self):
        # 店铺最早只能订明天，今天的格子点不动
        with at(2026, 9, 12):
            first, _ = watch._horizon(cfg(horizon_days=14))
        self.assertEqual(first, date(2026, 9, 13))

    def test_two_weeks_covers_through_day_14(self):
        with at(2026, 9, 12):
            first, last = watch._horizon(cfg(horizon_days=14))
        self.assertEqual((first, last), (date(2026, 9, 13), date(2026, 9, 26)))
        self.assertEqual((last - first).days + 1, 14)

    def test_until_extends_but_never_shrinks(self):
        with at(2026, 9, 12):
            _, extended = watch._horizon(cfg(horizon_days=14), date(2026, 11, 7))
            _, unchanged = watch._horizon(cfg(horizon_days=14), date(2026, 9, 15))
        self.assertEqual(extended, date(2026, 11, 7))
        self.assertEqual(unchanged, date(2026, 9, 26))


class TestFiltered(unittest.TestCase):
    """这个类的存在本身就是回归测试：_filtered 曾因拼错变量名直接 NameError。"""

    def test_runs_without_until_argument(self):
        with at(2026, 9, 12):
            got = watch._filtered(cfg(horizon_days=14), [slot("2026092011")])
        self.assertEqual(len(got), 1)

    def test_weekend_filter(self):
        with at(2026, 9, 12):
            got = watch._filtered(
                cfg(horizon_days=14),
                [slot("2026091813"), slot("2026092011")],  # 9/18 金, 9/20 日
            )
        self.assertEqual([s.start.day for s in got], [20])

    def test_drops_slots_beyond_horizon(self):
        # 10/3 是周六，但超出了 14 天窗口
        with at(2026, 9, 12):
            got = watch._filtered(cfg(horizon_days=14), [slot("2026100311")])
        self.assertEqual(got, [])

    def test_drops_slots_outside_hours(self):
        with at(2026, 9, 12):
            got = watch._filtered(
                cfg(horizon_days=14, hour_from=10, hour_to=18),
                [slot("2026092009"), slot("2026092018")],
            )
        self.assertEqual(got, [])


class TestCompose(unittest.TestCase):
    def test_single_menu_has_no_header(self):
        msg = watch._compose(cfg(), [slot("2026092712"), slot("2026092713")])
        self.assertEqual(msg.body, "9/27(日) 12:00-14:00")
        self.assertIn("airrsv.net", msg.url)

    def test_multiple_menus_are_labelled(self):
        other = Slot(
            start=slots_mod.datetime(2026, 9, 27, 15, tzinfo=JST),
            menu_id="s0000C8FBE",
            menu_name="カラーコース",
            mark=slots_mod.MARK_OPEN,
        )
        msg = watch._compose(cfg(), [slot("2026092712"), other])
        self.assertIn("【カット】", msg.body)
        self.assertIn("【カラーコース】", msg.body)

    def test_few_left_is_flagged(self):
        msg = watch._compose(cfg(), [slot("2026092712", MARK_FEW_LEFT)])
        self.assertIn("残りわずか", msg.body)


if __name__ == "__main__":
    unittest.main()
