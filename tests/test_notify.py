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
    KEY = "dK8sLp2QxV9mNt4RwZ7bYc"

    def test_app_copied_url(self):
        self.assertEqual(
            notify.split_bark_url(f"https://api.day.app/{self.KEY}"),
            ("https://api.day.app", self.KEY),
        )

    def test_trailing_slash(self):
        self.assertEqual(
            notify.split_bark_url(f"https://api.day.app/{self.KEY}/"),
            ("https://api.day.app", self.KEY),
        )

    def test_bare_key(self):
        self.assertEqual(
            notify.split_bark_url(self.KEY), ("https://api.day.app", self.KEY)
        )

    def test_example_body_text_is_ignored(self):
        """App 里连示例文字一起复制是最常见的填法。

        以前盲取最后一段，会把中文当成 key 拼进请求地址，导致
        UnicodeEncodeError 整轮崩掉。
        """
        with self.assertLogs("k_one.notify", level="WARNING"):
            got = notify.split_bark_url(f"https://api.day.app/{self.KEY}/推送内容")
        self.assertEqual(got, ("https://api.day.app", self.KEY))

    def test_example_title_and_body_are_ignored(self):
        with self.assertLogs("k_one.notify", level="WARNING"):
            got = notify.split_bark_url(
                f"https://api.day.app/{self.KEY}/推送标题/推送内容"
            )
        self.assertEqual(got, ("https://api.day.app", self.KEY))

    def test_resulting_url_is_ascii_safe(self):
        base, key = notify.split_bark_url(
            f"https://api.day.app/{self.KEY}/推送标题/推送内容"
        )
        f"{base}/push".encode("ascii")  # 不该抛 UnicodeEncodeError

    def test_self_hosted_with_subpath(self):
        self.assertEqual(
            notify.split_bark_url(f"https://bark.example.com/sub/{self.KEY}"),
            ("https://bark.example.com/sub", self.KEY),
        )

    def test_push_suffix_is_tolerated(self):
        self.assertEqual(
            notify.split_bark_url(f"https://api.day.app/{self.KEY}/push"),
            ("https://api.day.app", self.KEY),
        )

    def test_rejects_url_without_key(self):
        with self.assertRaises(notify.NotifyError):
            notify.split_bark_url("https://api.day.app")

    def test_rejects_non_ascii_only_path(self):
        with self.assertRaises(notify.NotifyError):
            notify.split_bark_url("https://api.day.app/推送内容")

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
        """behaviours: 渠道名 -> False(成功) / True(NotifyError) / 异常实例"""
        notify.CHANNELS.clear()
        for name, should_fail in behaviours.items():
            def fn(msg, env, _name=name, _fail=should_fail):
                self.calls.append(_name)
                if isinstance(_fail, BaseException):
                    raise _fail
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

    def test_unexpected_exception_does_not_crash_the_run(self):
        # 配错渠道（比如 BARK_URL 里混进中文）曾经让整个进程崩掉，
        # 连带其它渠道也发不出去
        self._install(a=UnicodeEncodeError("ascii", "x", 0, 1, "bad"), b=False)
        with self.assertLogs("k_one.notify", level="ERROR"):
            ok = notify.send(
                notify.Message("T", "B"), env={"A": "1", "B": "1"}, echo=False
            )
        self.assertTrue(ok)
        self.assertEqual(sorted(self.calls), ["a", "b"])

    def test_unconfigured_channel_is_skipped(self):
        self._install(a=False, b=False)
        notify.send(notify.Message("T", "B"), env={"A": "1"}, echo=False)
        self.assertEqual(self.calls, ["a"])


if __name__ == "__main__":
    unittest.main()
