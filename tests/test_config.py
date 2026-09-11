import os
import tempfile
import unittest
from pathlib import Path

from k_one import config


def write(dirpath, text):
    p = Path(dirpath) / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


class TestLoadConfig(unittest.TestCase):
    def test_repo_config_is_valid(self):
        """仓库里真实的 config.toml 必须能加载 —— 防止改坏了才在云端发现。"""
        cfg = config.load_config()
        self.assertTrue(cfg.watch.menus)
        self.assertEqual(cfg.watch.weekdays, ["sat", "sun"])

    def test_missing_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = config.load_config(Path(d) / "nope.toml")
            self.assertEqual(cfg.watch.menus, ["s0000A5844"])

    def test_partial_config_keeps_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = config.load_config(write(d, '[watch]\nhour_from = 12\n'))
            self.assertEqual(cfg.watch.hour_from, 12)
            self.assertEqual(cfg.watch.hour_to, 18)
            self.assertEqual(cfg.notify.renotify_after_hours, 24)

    def test_typo_in_key_is_rejected(self):
        # 悄悄忽略拼错的键 = 你以为改了配置其实没生效
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as ctx:
                config.load_config(write(d, '[watch]\nhorizon_day = 7\n'))
            self.assertIn("horizon_day", str(ctx.exception))

    def test_empty_menus_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                config.load_config(write(d, '[watch]\nmenus = []\n'))

    def test_inverted_hour_window_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                config.load_config(write(d, '[watch]\nhour_from = 18\nhour_to = 10\n'))

    def test_bad_weekday_rejected_at_load_time(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                config.load_config(write(d, '[watch]\nweekdays = ["funday"]\n'))

    def test_zero_horizon_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                config.load_config(write(d, '[watch]\nhorizon_days = 0\n'))


class TestLoadDotenv(unittest.TestCase):
    def setUp(self):
        self.saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def test_reads_values(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('# comment\nBARK_URL="https://x/y"\n\nEMPTY=\n', encoding="utf-8")
            os.environ.pop("BARK_URL", None)
            config.load_dotenv(p)
            self.assertEqual(os.environ["BARK_URL"], "https://x/y")
            self.assertNotIn("EMPTY", os.environ)

    def test_existing_env_wins(self):
        # CI 里 Secrets 已经注入，.env 不该覆盖它
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("BARK_URL=from-file\n", encoding="utf-8")
            os.environ["BARK_URL"] = "from-ci"
            config.load_dotenv(p)
            self.assertEqual(os.environ["BARK_URL"], "from-ci")

    def test_missing_file_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            config.load_dotenv(Path(d) / ".env")


if __name__ == "__main__":
    unittest.main()
