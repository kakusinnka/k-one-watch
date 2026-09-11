import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from k_one import state
from k_one.slots import JST, MARK_OPEN, Slot

NOW = datetime(2026, 9, 12, 14, 0, tzinfo=JST)


def slot(stamp: str, menu_id: str = "M1") -> Slot:
    return Slot(
        start=datetime.strptime(stamp, "%Y%m%d%H").replace(tzinfo=JST),
        menu_id=menu_id,
        menu_name="カット",
        mark=MARK_OPEN,
    )


class TestLoadSave(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "seen.json"
            state.save(p, {"a": "2026-09-12T14:00:00+09:00"})
            self.assertEqual(state.load(p), {"a": "2026-09-12T14:00:00+09:00"})

    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(state.load(Path(d) / "nope.json"), {})

    def test_corrupt_file_does_not_crash(self):
        # 状态文件坏掉最多让你多收一条重复通知，不该让监控停摆
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "seen.json"
            p.write_text("{not json", encoding="utf-8")
            with self.assertLogs("k_one.state", level="WARNING"):
                self.assertEqual(state.load(p), {})

    def test_non_dict_file_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "seen.json"
            p.write_text("[1, 2]", encoding="utf-8")
            self.assertEqual(state.load(p), {})


class TestSelectNew(unittest.TestCase):
    def test_unseen_slot_is_notified(self):
        got = state.select_new([slot("2026092712")], {}, renotify_after_hours=24, now=NOW)
        self.assertEqual(len(got), 1)

    def test_recently_notified_slot_is_skipped(self):
        seen = {"M1@2026092712": (NOW - timedelta(hours=1)).isoformat()}
        got = state.select_new(
            [slot("2026092712")], seen, renotify_after_hours=24, now=NOW
        )
        self.assertEqual(got, [])

    def test_stale_notification_is_repeated(self):
        seen = {"M1@2026092712": (NOW - timedelta(hours=25)).isoformat()}
        got = state.select_new(
            [slot("2026092712")], seen, renotify_after_hours=24, now=NOW
        )
        self.assertEqual(len(got), 1)

    def test_zero_means_never_repeat(self):
        seen = {"M1@2026092712": (NOW - timedelta(days=30)).isoformat()}
        got = state.select_new(
            [slot("2026092712")], seen, renotify_after_hours=0, now=NOW
        )
        self.assertEqual(got, [])

    def test_unparsable_timestamp_falls_back_to_notifying(self):
        seen = {"M1@2026092712": "garbage"}
        got = state.select_new(
            [slot("2026092712")], seen, renotify_after_hours=24, now=NOW
        )
        self.assertEqual(len(got), 1)

    def test_same_hour_different_menu_is_a_different_slot(self):
        seen = {"M1@2026092712": NOW.isoformat()}
        got = state.select_new(
            [slot("2026092712"), slot("2026092712", menu_id="M2")],
            seen,
            renotify_after_hours=24,
            now=NOW,
        )
        self.assertEqual([s.menu_id for s in got], ["M2"])


class TestPrune(unittest.TestCase):
    def test_drops_slots_that_are_gone(self):
        seen = {"M1@2026092712": NOW.isoformat(), "M1@2026092713": NOW.isoformat()}
        kept = state.prune(seen, [slot("2026092712")])
        self.assertEqual(list(kept), ["M1@2026092712"])

    def test_vanished_slot_can_be_notified_again_later(self):
        # 被抢走 -> prune 忘掉它 -> 别人取消后重新放出来 -> 再提醒一次
        seen = {"M1@2026092712": NOW.isoformat()}
        after_gone = state.prune(seen, [])
        again = state.select_new(
            [slot("2026092712")], after_gone, renotify_after_hours=24, now=NOW
        )
        self.assertEqual(len(again), 1)

    def test_empty_state_stays_empty(self):
        self.assertEqual(state.prune({}, [slot("2026092712")]), {})


class TestMarkNotified(unittest.TestCase):
    def test_records_timestamp(self):
        got = state.mark_notified({}, [slot("2026092712")], now=NOW)
        self.assertEqual(got, {"M1@2026092712": "2026-09-12T14:00:00+09:00"})

    def test_does_not_mutate_input(self):
        seen = {}
        state.mark_notified(seen, [slot("2026092712")], now=NOW)
        self.assertEqual(seen, {})

    def test_overwrites_previous_timestamp(self):
        seen = {"M1@2026092712": "2026-09-01T00:00:00+09:00"}
        got = state.mark_notified(seen, [slot("2026092712")], now=NOW)
        self.assertEqual(got["M1@2026092712"], "2026-09-12T14:00:00+09:00")


if __name__ == "__main__":
    unittest.main()
