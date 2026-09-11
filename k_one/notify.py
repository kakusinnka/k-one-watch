"""推送通知：Bark / Server酱 / PushPlus / 邮件 / 终端。

哪个渠道的环境变量填了就启用哪个，可以同时填多个做双保险。
一个渠道挂掉不影响其它渠道；全挂才算失败。
"""

from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage

log = logging.getLogger(__name__)

TIMEOUT = 15


@dataclass
class Message:
    title: str
    body: str
    url: str = ""

    def text(self) -> str:
        return f"{self.body}\n\n{self.url}".strip()


class NotifyError(RuntimeError):
    pass


def _post(url: str, data: bytes, headers: dict[str, str]) -> str:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise NotifyError(f"HTTP {exc.code}: {exc.read()[:200]!r}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise NotifyError(str(exc)) from exc


def _post_json(url: str, payload: dict) -> str:
    return _post(
        url,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        {"Content-Type": "application/json; charset=utf-8"},
    )


def _post_form(url: str, payload: dict) -> str:
    return _post(
        url,
        urllib.parse.urlencode(payload).encode("utf-8"),
        {"Content-Type": "application/x-www-form-urlencoded"},
    )


# --------------------------------------------------------------------------
# 各渠道。签名统一为 (msg, env) -> None，失败抛 NotifyError。
# --------------------------------------------------------------------------


#: Bark 的 device key 是一串字母数字（通常 20~24 位）
_BARK_KEY_RE = re.compile(r"[A-Za-z0-9]{8,}")


def split_bark_url(value: str) -> tuple[str, str]:
    """把用户填的 BARK_URL 拆成（服务器地址, device_key）。

    App 里「复制」出来的往往连示例文字一起带上了，例如
    ``https://api.day.app/<key>/推送标题/推送内容``。所以这里按 key 的形状去认，
    而不是盲取最后一段 —— 否则中文会被当成 key 拼进请求地址。

    只粘 key、自建服务器带子路径，也都认。
    """
    value = value.strip().rstrip("/")
    if not value:
        raise NotifyError("BARK_URL 是空的")
    if "://" not in value:
        value = "https://api.day.app/" + value.lstrip("/")

    parts = urllib.parse.urlsplit(value)
    segments = [seg for seg in parts.path.split("/") if seg and seg != "push"]
    key_positions = [
        i for i, seg in enumerate(segments) if _BARK_KEY_RE.fullmatch(seg)
    ]
    if not key_positions:
        raise NotifyError(
            f"BARK_URL 里找不到 device key（应该是一串字母数字）：{value!r}"
        )

    at = key_positions[-1]
    ignored = segments[at + 1 :]
    if ignored:
        # 多半是 App 里一起复制来的示例推送内容，不该进请求地址
        log.warning("BARK_URL 末尾的 %s 已忽略，只用 device key", "/".join(ignored))

    base = urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, "/".join(segments[:at]), "", "")
    )
    return base, segments[at]


def send_bark(msg: Message, env: dict[str, str]) -> None:
    base, device_key = split_bark_url(env["BARK_URL"])
    payload = {
        "device_key": device_key,
        "title": msg.title,
        "body": msg.body,
        "group": "k-one-watch",
        # 空位会被抢，所以用持续响铃的提示音 + 时效性通知
        "sound": "alarm",
        "level": "timeSensitive",
    }
    if msg.url:
        payload["url"] = msg.url
    body = _post_json(f"{base}/push", payload)
    if '"code":200' not in body.replace(" ", ""):
        raise NotifyError(f"Bark 返回异常：{body[:200]}")


def send_serverchan(msg: Message, env: dict[str, str]) -> None:
    key = env["SERVERCHAN_KEY"]
    body = _post_form(
        f"https://sctapi.ftqq.com/{urllib.parse.quote(key)}.send",
        {"title": msg.title, "desp": msg.text()},
    )
    if '"code":0' not in body.replace(" ", ""):
        raise NotifyError(f"Server酱 返回异常：{body[:200]}")


def send_pushplus(msg: Message, env: dict[str, str]) -> None:
    body = _post_json(
        "https://www.pushplus.plus/send",
        {
            "token": env["PUSHPLUS_TOKEN"],
            "title": msg.title,
            "content": msg.text(),
            "template": "txt",
        },
    )
    if '"code":200' not in body.replace(" ", ""):
        raise NotifyError(f"PushPlus 返回异常：{body[:200]}")


def send_email(msg: Message, env: dict[str, str]) -> None:
    mail = EmailMessage()
    mail["Subject"] = msg.title
    mail["From"] = env["SMTP_USER"]
    mail["To"] = env["SMTP_TO"]
    mail.set_content(msg.text())

    host = env["SMTP_HOST"]
    port = int(env.get("SMTP_PORT") or 465)
    try:
        if port == 587:
            with smtplib.SMTP(host, port, timeout=TIMEOUT) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(env["SMTP_USER"], env["SMTP_PASS"])
                smtp.send_message(mail)
        else:
            with smtplib.SMTP_SSL(
                host, port, timeout=TIMEOUT, context=ssl.create_default_context()
            ) as smtp:
                smtp.login(env["SMTP_USER"], env["SMTP_PASS"])
                smtp.send_message(mail)
    except (smtplib.SMTPException, OSError) as exc:
        raise NotifyError(str(exc)) from exc


def send_console(msg: Message, env: dict[str, str]) -> None:
    print("-" * 56)
    print(msg.title)
    print(msg.text())
    print("-" * 56)


#: 渠道名 -> (所需环境变量, 发送函数)。所需变量全部非空才会启用。
CHANNELS: dict[str, tuple[tuple[str, ...], object]] = {
    "bark": (("BARK_URL",), send_bark),
    "serverchan": (("SERVERCHAN_KEY",), send_serverchan),
    "pushplus": (("PUSHPLUS_TOKEN",), send_pushplus),
    "email": (("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_TO"), send_email),
}


def configured(env: dict[str, str] | None = None) -> list[str]:
    """列出当前环境下已配置好的渠道名。"""
    env = os.environ if env is None else env
    return [
        name
        for name, (required, _) in CHANNELS.items()
        if all(env.get(k) for k in required)
    ]


def send(msg: Message, *, env: dict[str, str] | None = None, echo: bool = True) -> bool:
    """推送到所有已配置渠道。

    返回 True 仅当**至少有一个渠道真的送达**。没配置渠道也算 False —— 终端打印
    不等于通知到了你，调用方据此不写 state，这样你之后填好 key，这批空位还会
    正常提醒一次，而不是被当成"已通知"压着。
    """
    env = os.environ if env is None else env
    names = configured(env)

    if echo:
        send_console(msg, env)

    if not names:
        log.warning(
            "没有配置任何推送渠道，只在终端输出（本轮不计入已通知）。见 .env.example"
        )
        return False

    ok = 0
    for name in names:
        _, fn = CHANNELS[name]
        try:
            fn(msg, env)
        except NotifyError as exc:
            log.error("推送到 %s 失败：%s", name, exc)
        except Exception:
            # 配错渠道（比如 URL 里混进了中文）不该把整轮监控带崩，
            # 其它渠道该照发，状态该照走
            log.exception("推送到 %s 时发生意外错误", name)
        else:
            ok += 1
            log.info("已推送到 %s", name)

    if ok == 0:
        log.error("全部 %d 个渠道推送失败", len(names))
    return ok > 0
