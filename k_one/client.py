"""Air リザーブ 预约日历接口客户端。

接口是 JSONP：
    GET /k-one111/stateful/calendar/staff/searchStaffMenuResrc
        ?menuId=...&bookingFromDt=...&bookingToDt=...&refineRange=&_=<ts>
返回 ``/**/callback({...})``，无需 cookie / CSRF。

注意：无论请求区间多宽，响应里的 ``listModalIsActive`` 恒为 168 条
（7 天 x 24 小时）。要覆盖更长的周期，必须按周多次请求。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

SHOP = "k-one111"
BASE = f"https://airrsv.net/{SHOP}"
CALENDAR_URL = f"{BASE}/calendar"
API_URL = f"{BASE}/stateful/calendar/staff/searchStaffMenuResrc"

#: 一次响应覆盖的天数（服务端硬上限）
DAYS_PER_REQUEST = 7

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

TIMEOUT = 20
RETRY_BACKOFF = (2, 5)  # 失败后的重试间隔（秒），长度即重试次数
#: 连续请求之间的间隔，别把人家站点当压测靶子
POLITE_DELAY = 1.5


class AirReserveError(RuntimeError):
    """接口返回了失败响应，或响应无法解析。"""


def unwrap_jsonp(raw: str) -> dict:
    """剥掉 ``/**/callback(...)`` 外壳，返回里面的 JSON。"""
    try:
        start = raw.index("(") + 1
        end = raw.rindex(")")
    except ValueError as exc:
        raise AirReserveError(f"响应不是 JSONP 格式：{raw[:120]!r}") from exc
    try:
        return json.loads(raw[start:end])
    except json.JSONDecodeError as exc:
        raise AirReserveError(f"JSONP 内容不是合法 JSON：{exc}") from exc


def _build_url(menu_id: str, week_start: date) -> str:
    week_end = week_start + timedelta(days=DAYS_PER_REQUEST - 1)
    params = urllib.parse.urlencode(
        {
            "menuId": menu_id,
            "bookingFromDt": week_start.strftime("%Y%m%d") + "000000",
            "bookingToDt": week_end.strftime("%Y%m%d") + "240000",
            "refineRange": "",
            "_": int(time.time() * 1000),
        }
    )
    return f"{API_URL}?{params}"


def _get(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": CALENDAR_URL,
            "Accept": "*/*",
            "Accept-Language": "ja,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8")


def fetch_week(menu_id: str, week_start: date) -> dict:
    """取回 ``week_start`` 起 7 天的日历数据，返回响应里的 ``dto``。

    网络错误会按 :data:`RETRY_BACKOFF` 重试；重试耗尽后抛
    :class:`AirReserveError`。
    """
    url = _build_url(menu_id, week_start)
    last_exc: Exception | None = None

    for attempt in range(len(RETRY_BACKOFF) + 1):
        if attempt:
            wait = RETRY_BACKOFF[attempt - 1]
            log.warning("请求失败（%s），%s 秒后重试", last_exc, wait)
            time.sleep(wait)
        try:
            payload = unwrap_jsonp(_get(url))
        except (urllib.error.URLError, OSError, AirReserveError) as exc:
            last_exc = exc
            continue

        code = payload.get("responseCode") or {}
        if not code.get("success"):
            # 业务失败重试也没用，直接抛
            raise AirReserveError(
                f"接口返回失败：code={code.get('code')} messages={payload.get('messages')}"
            )
        dto = payload.get("dto")
        if not isinstance(dto, dict):
            raise AirReserveError("响应里没有 dto")
        return dto

    raise AirReserveError(f"请求 {menu_id} @ {week_start} 重试耗尽：{last_exc}")


def covered_range(dto: dict) -> tuple[date, date] | None:
    """响应实际覆盖了哪段日期。

    服务端会把请求窗口夹到可预约期内 —— 例如请求 9/13 起的一周，实际返回的是
    9/14~9/20（9/14 是 bookingAvailableFrom）。所以翻页必须以实际返回的范围
    为准往前推，不能盲目按 7 天步进，否则会漏天或重复抓。
    """
    entries = dto.get("calendar", {}).get("listModalIsActive") or []
    stamps = [e["modalTime"] for e in entries if e.get("modalTime")]
    if not stamps:
        return None
    return (
        datetime.strptime(min(stamps)[:8], "%Y%m%d").date(),
        datetime.strptime(max(stamps)[:8], "%Y%m%d").date(),
    )
