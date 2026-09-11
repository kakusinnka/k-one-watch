import json
import unittest
from datetime import date
from pathlib import Path

from k_one import client


class TestUnwrapJsonp(unittest.TestCase):
    def test_strips_callback_wrapper(self):
        self.assertEqual(
            client.unwrap_jsonp('/**/callback({"a": 1})'), {"a": 1}
        )

    def test_tolerates_parens_inside_payload(self):
        raw = '/**/callback({"name": "コールドコース（ロッド）"})'
        self.assertEqual(
            client.unwrap_jsonp(raw)["name"], "コールドコース（ロッド）"
        )

    def test_rejects_non_jsonp(self):
        with self.assertRaises(client.AirReserveError):
            client.unwrap_jsonp("<html>error page</html>")

    def test_rejects_malformed_json(self):
        with self.assertRaises(client.AirReserveError):
            client.unwrap_jsonp("/**/callback({nope})")


class TestCoveredRange(unittest.TestCase):
    def test_reads_actual_span_from_response(self):
        dto = {
            "calendar": {
                "listModalIsActive": [
                    {"modalTime": "20260914000000", "isActive": False},
                    {"modalTime": "20260920230000", "isActive": True},
                ]
            }
        }
        self.assertEqual(
            client.covered_range(dto), (date(2026, 9, 14), date(2026, 9, 20))
        )

    def test_detects_server_side_clamping(self):
        """请求 9/13 起的一周，服务端夹到可预约期起点 9/14 —— 翻页得认这个。"""
        dto = json.loads(
            (Path(__file__).parent / "fixtures" / "week_cut.json").read_text("utf-8")
        )
        self.assertEqual(
            client.covered_range(dto), (date(2026, 9, 21), date(2026, 9, 27))
        )

    def test_unordered_entries(self):
        dto = {
            "calendar": {
                "listModalIsActive": [
                    {"modalTime": "20260920230000"},
                    {"modalTime": "20260914000000"},
                ]
            }
        }
        self.assertEqual(
            client.covered_range(dto), (date(2026, 9, 14), date(2026, 9, 20))
        )

    def test_empty_response_returns_none(self):
        self.assertIsNone(client.covered_range({"calendar": {"listModalIsActive": []}}))
        self.assertIsNone(client.covered_range({}))


class TestBuildUrl(unittest.TestCase):
    def test_covers_seven_days_inclusive(self):
        url = client._build_url("s0000A5844", date(2026, 9, 21))
        self.assertIn("menuId=s0000A5844", url)
        self.assertIn("bookingFromDt=20260921000000", url)
        # 到第 7 天的 24:00，与页面翻页时发出的请求一致
        self.assertIn("bookingToDt=20260927240000", url)


if __name__ == "__main__":
    unittest.main()
