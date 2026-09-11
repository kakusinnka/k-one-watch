"""把接口返回的 dto 解析成空位，再按配置过滤、合并成人话。

时区固定用 +09:00 表示 JST。日本不实行夏令时，固定偏移与 ``Asia/Tokyo``
恒等价，而且不依赖 Windows 上缺失的 tzdata。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from itertools import groupby

log = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9), "JST")

#: availabilityKbnCd 的含义（已与 isActive 交叉验证）
MARK_OPEN = "1"       # ○ 予約可能
MARK_FEW_LEFT = "2"   # △ 残りわずか
MARK_CLOSED = "3"     # x 予約できません

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_WEEKDAY_FULL = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
)
#: 只认三字母缩写和完整拼写，"satrday" 这种拼错要报错而不是被猜成 sat
_WEEKDAY_ALIASES = {
    **{k: i for i, k in enumerate(_WEEKDAY_KEYS)},
    **{k: i for i, k in enumerate(_WEEKDAY_FULL)},
}
#: 消息里用日语星期，和店铺页面保持一致
_WEEKDAY_JA = ("月", "火", "水", "木", "金", "土", "日")


@dataclass(frozen=True, order=True)
class Slot:
    """一个可预约的整点时段。"""

    start: datetime
    menu_id: str
    menu_name: str
    mark: str = MARK_OPEN

    @property
    def key(self) -> str:
        """state 文件里的稳定标识。"""
        return f"{self.menu_id}@{self.start.strftime('%Y%m%d%H')}"

    @property
    def few_left(self) -> bool:
        return self.mark == MARK_FEW_LEFT

    def label(self) -> str:
        """``9/19(土) 10:00``，用于单条展示。"""
        d = self.start
        return f"{d.month}/{d.day}({_WEEKDAY_JA[d.weekday()]}) {d:%H:%M}"


def _parse_stamp(stamp: str) -> datetime:
    """``20260916130000`` -> JST datetime。"""
    return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=JST)


def parse(dto: dict) -> list[Slot]:
    """从一次响应里取出全部可预约时段。

    以 ``listModalIsActive`` 的 ``isActive`` 为准（这是页面真正用来决定能否
    点击的字段），再从 ``listHourlyAvailabilityMark`` 补上 ○/△ 标记。
    """
    menu = dto.get("menuInfoDto") or {}
    menu_id = menu.get("menuId") or ""
    menu_name = menu.get("menuNm") or menu_id

    marks = {
        m["frameTime"]: m.get("availabilityKbnCd")
        for m in dto.get("calendar", {}).get("listHourlyAvailabilityMark") or []
        if m.get("frameTime")
    }

    slots = []
    for entry in dto.get("calendar", {}).get("listModalIsActive") or []:
        if not entry.get("isActive"):
            continue
        stamp = entry.get("modalTime")
        if not stamp:
            continue
        slots.append(
            Slot(
                start=_parse_stamp(stamp),
                menu_id=menu_id,
                menu_name=menu_name,
                mark=marks.get(stamp) or MARK_OPEN,
            )
        )
    return sorted(slots)


def now_jst() -> datetime:
    return datetime.now(JST)


def weekday_mask(names: list[str]) -> set[int] | None:
    """``["sat","sun"]`` -> ``{5, 6}``；空列表 -> ``None``（不限）。"""
    if not names:
        return None
    mask = set()
    for name in names:
        index = _WEEKDAY_ALIASES.get(name.strip().lower())
        if index is None:
            raise ValueError(
                f"config.toml 里的 weekdays 有无法识别的值：{name!r}，"
                f"可用值：{', '.join(_WEEKDAY_KEYS)}"
            )
        mask.add(index)
    return mask


def apply_filters(
    slots: list[Slot],
    *,
    weekdays: list[str],
    hour_from: int,
    hour_to: int,
    include_few_left: bool,
    date_from: date,
    date_to: date,
) -> list[Slot]:
    """按星期 / 小时 / 日期区间 / ○△ 过滤。``date_to`` 含当天。"""
    mask = weekday_mask(weekdays)
    kept = []
    for s in slots:
        day = s.start.date()
        if not (date_from <= day <= date_to):
            continue
        if mask is not None and s.start.weekday() not in mask:
            continue
        if not (hour_from <= s.start.hour < hour_to):
            continue
        if s.few_left and not include_few_left:
            continue
        kept.append(s)
    return kept


def merge_runs(slots: list[Slot]) -> list[str]:
    """把同一天连续的整点合并成区间，返回逐日的可读行。

    ``10:00, 11:00, 12:00, 15:00`` -> ``9/19(土) 10:00-13:00 / 15:00-16:00``
    （结束时间是该时段的下一个整点，也就是实际占用到什么时候。）
    """
    lines = []
    for day, day_slots in groupby(sorted(slots), key=lambda s: s.start.date()):
        day_slots = list(day_slots)
        spans: list[list[Slot]] = []
        for s in day_slots:
            if spans and s.start - spans[-1][-1].start == timedelta(hours=1):
                spans[-1].append(s)
            else:
                spans.append([s])

        parts = []
        for span in spans:
            end = span[-1].start + timedelta(hours=1)
            text = f"{span[0].start:%H:%M}-{end:%H:%M}"
            if any(s.few_left for s in span):
                text += "(残りわずか)"
            parts.append(text)

        head = f"{day.month}/{day.day}({_WEEKDAY_JA[day.weekday()]})"
        lines.append(f"{head} {' / '.join(parts)}")
    return lines
