import unittest

from k_one import notify


class TestConfigured(unittest.TestCase):
    def test_detects_each_channel(self):
        self.assertEqual(notify.configured({"BARK_URL": "https://x"}), ["bark"])
        self.assertEqual(notify.configured({"SERVERCHAN_KEY": "SCT1"}), ["serverchan"])
        self.assertEqual(notify.configured({"PUSHPLUS_TOKEN": "t"}), ["pushplus"])

    def test_empty_env_means_none(self):
        self.assertEqual(notify.configured({}), [])

    def test_blank_value_does_not_count(self):
        # .env.example 里留空的行不该被当成"已配置"
        self.assertEqual(notify.configured({"BARK_URL": ""}), [])

    def test_email_needs_all_parts(self):
        partial = {"SMTP_HOST": "smtp.gmail.com", "SMTP_USER": "a@b.c"}
        self.assertEqual(notify.configured(partial), [])
        full = {**partial, "SMTP_PASS": "p", "SMTP_TO": "a@b.c"}
        self.assertEqual(notify.configured(full), ["email"])

    def test_multiple_channels(self):
        self.assertEqual(
            sorted(notify.configured({"BARK_URL": "x", "PUSHPLUS_TOKEN": "y"})),
            ["bark", "pushplus"],
        )


class TestSplitBarkUrl(unittest.TestCase):
    def test_app_copied_url(self):
        self.assertEqual(
            notify.split_bark_url("https://api.day.app/AbC123"),
            ("https://api.day.app", "AbC123"),
        )

    def test_trailing_slash(self):
        self.assertEqual(
            notify.split_bark_url("https://api.day.app/AbC123/"),
            ("https://api.day.app", "AbC123"),
        )

    def test_bare_key(self):
        self.assertEqual(
            notify.split_bark_url("AbC123"), ("https://api.day.app", "AbC123")
        )

    def test_self_hosted_with_subpath(self):
        self.assertEqual(
            notify.split_bark_url("https://bark.example.com/sub/KeY9"),
            ("https://bark.example.com/sub", "KeY9"),
        )

    def test_rejects_url_without_key(self):
        with self.assertRaises(notify.NotifyError):
            notify.split_bark_url("https://api.day.app")

    def test_rejects_push_suffix(self):
        # 把 /push 一起粘进来是常见误操作，宁可报错也别静默发到错地址
        with self.assertRaises(notify.NotifyError):
            notify.split_bark_url("https://api.day.app/push")

    def test_rejects_empty(self):
        with self.assertRaises(notify.NotifyError):
            notify.split_bark_url("   ")


class TestMessage(unittest.TestCase):
    def test_text_appends_url(self):
        msg = notify.Message(title="T", body="9/27(日) 12:00-14:00", url="https://x")
        self.assertEqual(msg.text(), "9/27(日) 12:00-14:00\n\nhttps://x")

    def test_text_without_url(self):
        self.assertEqual(notify.Message(title="T", body="B").text(), "B")


class TestSendDispatch(unittest.TestCase):
    """用假渠道验证分发/容错逻辑，不触网。"""

    def setUp(self):
        self.real = notify.CHANNELS.copy()
        self.calls = []

    def tearDown(self):
        notify.CHANNELS.clear()
        notify.CHANNELS.update(self.real)

    def _install(self, **behaviours):
        notify.CHANNELS.clear()
        for name, should_fail in behaviours.items():
            def fn(msg, env, _name=name, _fail=should_fail):
                self.calls.append(_name)
                if _fail:
                    raise notify.NotifyError("boom")

            notify.CHANNELS[name] = ((name.upper(),), fn)

    def test_all_configured_channels_are_called(self):
        self._install(a=False, b=False)
        ok = notify.send(
            notify.Message("T", "B"), env={"A": "1", "B": "1"}, echo=False
        )
        self.assertTrue(ok)
        self.assertEqual(sorted(self.calls), ["a", "b"])

    def test_one_failure_does_not_block_the_other(self):
        self._install(a=True, b=False)
        with self.assertLogs("k_one.notify", level="ERROR"):
            ok = notify.send(
                notify.Message("T", "B"), env={"A": "1", "B": "1"}, echo=False
            )
        self.assertTrue(ok)
        self.assertEqual(sorted(self.calls), ["a", "b"])

    def test_total_failure_reports_false(self):
        # 调用方据此跳过写 state，免得空位被记成"已通知"而永远漏掉
        self._install(a=True, b=True)
        with self.assertLogs("k_one.notify", level="ERROR"):
            ok = notify.send(
                notify.Message("T", "B"), env={"A": "1", "B": "1"}, echo=False
            )
        self.assertFalse(ok)

    def test_no_channels_counts_as_not_delivered(self):
        # 终端打印不等于通知到了人，所以不能算送达 ——
        # 否则用户配好 key 之前的空位会被永久记成"已通知"
        self._install(a=False)
        with self.assertLogs("k_one.notify", level="WARNING"):
            ok = notify.send(notify.Message("T", "B"), env={}, echo=False)
        self.assertFalse(ok)
        self.assertEqual(self.calls, [])

    def test_unconfigured_channel_is_skipped(self):
        self._install(a=False, b=False)
        notify.send(notify.Message("T", "B"), env={"A": "1"}, echo=False)
        self.assertEqual(self.calls, ["a"])


if __name__ == "__main__":
    unittest.main()
