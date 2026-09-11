#!/usr/bin/env python3
"""k-one-watch —— 监控 HAIR STAGE K-ONE 的预约空位，有空位就通知你。

只读工具：它只查询公开的预约日历，从不替你提交预约。

    python watch.py check              # 抓取 -> 比对 -> 推送新空位（定时任务跑这个）
    python watch.py check --dry-run    # 只打印本轮会推什么，不推送也不写状态
    python watch.py show               # 列出当前所有符合条件的空位
    python watch.py show --all         # 连被过滤掉的空位一起列出，用来核对过滤器
    python watch.py test-notify        # 给已配置的渠道发一条测试消息
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta

from k_one import client, config, notify, slots as slots_mod, state
from k_one.slots import Slot

log = logging.getLogger("k-one-watch")


def _horizon(cfg: config.Config) -> tuple[date, date]:
    """要覆盖的日期区间（含首尾）。店铺最早只能订明天，所以从明天起算。"""
    first = (slots_mod.now_jst() + timedelta(days=1)).date()
    return first, first + timedelta(days=cfg.watch.horizon_days - 1)


def _collect(cfg: config.Config) -> tuple[list[Slot], bool]:
    """抓取全部菜单 x 全部周次，返回（去重后的空位, 本轮是否完整）。

    某一周抓失败不会让整轮报废 —— 剩下的照常通知，但会把"不完整"传出去，
    调用方据此跳过 prune，免得把没抓到的条目误当成"已被抢走"。
    """
    first_day, last_day = _horizon(cfg)
    found: list[Slot] = []
    complete = True
    requests = 0

    for menu_id in cfg.watch.menus:
        cursor = first_day
        while cursor <= last_day:
            if requests:
                time.sleep(client.POLITE_DELAY)
            requests += 1
            try:
                dto = client.fetch_week(menu_id, cursor)
            except client.AirReserveError as exc:
                log.error("抓取 %s @ %s 失败：%s", menu_id, cursor, exc)
                complete = False
                break

            found.extend(slots_mod.parse(dto))

            covered = client.covered_range(dto)
            if covered is None:
                log.warning("%s @ %s 没有返回任何时段，停止翻页", menu_id, cursor)
                complete = False
                break
            # 服务端会把窗口夹到可预约期内，所以按它实际返回的末日往前推。
            # 万一它返回的范围没能推进游标，就硬走一周，避免死循环。
            next_cursor = covered[1] + timedelta(days=1)
            cursor = next_cursor if next_cursor > cursor else cursor + timedelta(
                days=client.DAYS_PER_REQUEST
            )

    unique = sorted(set(found))
    log.info(
        "发出 %d 次请求，拿到 %d 个空位（完整=%s）", requests, len(unique), complete
    )
    return unique, complete


def _filtered(cfg: config.Config, all_slots: list[Slot]) -> list[Slot]:
    first_day, last_day = _horizon(cfg)
    return slots_mod.apply_filters(
        all_slots,
        weekdays=cfg.watch.weekdays,
        hour_from=cfg.watch.hour_from,
        hour_to=cfg.watch.hour_to,
        include_few_left=cfg.watch.include_few_left,
        date_from=first_day,
        date_to=last_day,
    )


def _compose(cfg: config.Config, to_notify: list[Slot]) -> notify.Message:
    by_menu: dict[str, list[Slot]] = {}
    for s in to_notify:
        by_menu.setdefault(s.menu_name, []).append(s)

    blocks = []
    for menu_name, menu_slots in by_menu.items():
        lines = slots_mod.merge_runs(menu_slots)
        head = f"【{menu_name}】" if len(by_menu) > 1 else ""
        blocks.append((head + "\n" if head else "") + "\n".join(lines))

    return notify.Message(
        title=cfg.notify.title,
        body="\n".join(blocks),
        url=cfg.notify.booking_url,
    )


def cmd_check(args, cfg: config.Config) -> int:
    all_slots, complete = _collect(cfg)
    current = _filtered(cfg, all_slots)
    log.info("符合条件的空位 %d 个", len(current))

    seen = state.load(config.STATE_PATH)
    to_notify = state.select_new(
        current, seen, renotify_after_hours=cfg.notify.renotify_after_hours
    )

    if not to_notify:
        print(f"无新增空位（当前符合条件的空位 {len(current)} 个）")
    else:
        msg = _compose(cfg, to_notify)
        if args.dry_run:
            print("[dry-run] 本轮会推送：")
            notify.send_console(msg, {})
            return 0
        if not notify.send(msg, echo=True):
            # 没送达就别记成"已通知"，否则这些空位再也不会提醒你
            if notify.configured():
                log.error("推送全部失败，本轮不更新状态")
                return 1
            log.warning("未送达任何渠道，本轮不更新状态")
            return 0
        seen = state.mark_notified(seen, to_notify)

    if args.dry_run:
        return 0

    updated = state.prune(seen, current) if complete else seen
    if updated != state.load(config.STATE_PATH):
        state.save(config.STATE_PATH, updated)
        log.info("状态已更新：%d 条", len(updated))
    return 0


def cmd_show(args, cfg: config.Config) -> int:
    all_slots, _ = _collect(cfg)
    shown = all_slots if args.all else _filtered(cfg, all_slots)

    if not shown:
        print("当前没有空位" if args.all else "当前没有符合条件的空位")
        return 0

    by_menu: dict[str, list[Slot]] = {}
    for s in shown:
        by_menu.setdefault(s.menu_name, []).append(s)
    for menu_name, menu_slots in by_menu.items():
        print(f"\n【{menu_name}】{len(menu_slots)} 个空位")
        for line in slots_mod.merge_runs(menu_slots):
            print("  " + line)
    print(f"\n{cfg.notify.booking_url}")
    return 0


def cmd_test_notify(args, cfg: config.Config) -> int:
    names = notify.configured()
    if not names:
        print("没有检测到任何已配置的推送渠道。")
        print("本地：复制 .env.example 为 .env 并填写；云端：填 GitHub Secrets。")
        return 1
    print(f"已配置的渠道：{', '.join(names)}")
    msg = notify.Message(
        title=cfg.notify.title,
        body="这是一条测试消息。收到就说明推送通了，可以放心让它跑了。",
        url=cfg.notify.booking_url,
    )
    return 0 if notify.send(msg, echo=True) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watch.py", description="监控 K-ONE 预约空位（只读，不会替你预约）"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="打印调试日志")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="抓取并推送新出现的空位")
    p_check.add_argument(
        "--dry-run", action="store_true", help="只打印会推什么，不推送也不写状态"
    )
    p_check.set_defaults(func=cmd_check)

    p_show = sub.add_parser("show", help="列出当前空位")
    p_show.add_argument(
        "--all", action="store_true", help="忽略过滤条件，列出全部空位"
    )
    p_show.set_defaults(func=cmd_show)

    p_test = sub.add_parser("test-notify", help="给已配置的渠道发测试消息")
    p_test.set_defaults(func=cmd_test_notify)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    config.load_dotenv()
    try:
        cfg = config.load_config()
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    return args.func(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
