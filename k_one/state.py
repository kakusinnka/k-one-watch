"""记住已经通知过哪些空位，避免每 15 分钟重复轰炸。

state/seen.json 形如::

    {"s0000A5844@2026091910": "2026-09-12T14:03:11+09:00"}

键是空位标识，值是最后一次通知它的时间。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .slots import JST, Slot

log = logging.getLogger(__name__)


def load(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # 状态文件坏了不该让监控停摆，最多重复推一次
        log.warning("%s 解析失败，按空状态处理", path)
        return {}
    return data if isinstance(data, dict) else {}


def save(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def select_new(
    current: list[Slot],
    seen: dict[str, str],
    *,
    renotify_after_hours: int,
    now: datetime | None = None,
) -> list[Slot]:
    """挑出需要推送的空位。

    - 从没通知过的 -> 推
    - 通知过、但现在仍空着且已过 ``renotify_after_hours`` -> 再推一次
      （``0`` 表示永不重复提醒）
    """
    now = now or datetime.now(JST)
    out = []
    for slot in current:
        last = seen.get(slot.key)
        if last is None:
            out.append(slot)
            continue
        if renotify_after_hours <= 0:
            continue
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            out.append(slot)
            continue
        if now - last_dt >= timedelta(hours=renotify_after_hours):
            out.append(slot)
    return out


def prune(seen: dict[str, str], current: list[Slot]) -> dict[str, str]:
    """只保留当前仍然空着的条目。

    空位被别人抢走（或时间已过）后从 state 里移除，这样它日后要是被取消、
    重新放出来，能再提醒你一次。

    调用方注意：``current`` 必须是一轮**完整**抓取的结果。有任何一周抓取失败
    时不要 prune，否则那周的条目会被误删，下一轮又全部重推一遍。
    """
    alive = {s.key for s in current}
    return {k: v for k, v in seen.items() if k in alive}


def mark_notified(
    seen: dict[str, str], slots: list[Slot], *, now: datetime | None = None
) -> dict[str, str]:
    now = now or datetime.now(JST)
    stamp = now.isoformat(timespec="seconds")
    updated = dict(seen)
    for slot in slots:
        updated[slot.key] = stamp
    return updated
