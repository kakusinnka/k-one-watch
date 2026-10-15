"""加载 config.toml 与 .env / 环境变量。

配置分两半：
  - config.toml —— 监控什么，进公开仓库，绝不含密钥
  - .env / 环境变量 —— 推送密钥，本地 .env 已 gitignore，云端走 GitHub Secrets
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"
ENV_PATH = ROOT / ".env"
STATE_PATH = ROOT / "state" / "seen.json"


@dataclass
class Rule:
    """一条筛选规则：某些星期的某个时间段。

    ``weekdays`` 留空表示不限星期。``hour_from``/``hour_to`` 针对空位的**开始
    时间**，半开区间 ``[hour_from, hour_to)`` —— 所以「只要 17:00 那一档」写成
    ``hour_from = 17`` / ``hour_to = 18``。
    """

    name: str = ""
    weekdays: list[str] = field(default_factory=list)
    hour_from: int = 10
    hour_to: int = 18

    def describe(self) -> str:
        who = "/".join(self.weekdays) if self.weekdays else "每天"
        return self.name or f"{who} {self.hour_from}:00-{self.hour_to}:00"


def _default_rules() -> list[Rule]:
    return [
        Rule(name="周末全天", weekdays=["sat", "sun"], hour_from=10, hour_to=18),
        Rule(name="下班后", weekdays=[], hour_from=17, hour_to=18),
    ]


@dataclass
class WatchConfig:
    menus: list[str] = field(default_factory=lambda: ["s0000A5844"])
    horizon_days: int = 35
    include_few_left: bool = True
    #: 命中**任意一条**规则就算符合条件
    rules: list[Rule] = field(default_factory=_default_rules)


@dataclass
class NotifyConfig:
    title: str = "K-ONE 有空位"
    booking_url: str = "https://airrsv.net/k-one111/calendar"
    renotify_after_hours: int = 24


@dataclass
class Config:
    watch: WatchConfig = field(default_factory=WatchConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)


def _known_fields(cls, raw: dict, where: str) -> dict:
    """只取 dataclass 认识的键，多余的键报错而不是被悄悄吞掉。"""
    allowed = {f.name for f in cls.__dataclass_fields__.values()}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(
            f"config.toml 的 [{where}] 里有无法识别的配置项：{sorted(unknown)}"
        )
    return {k: v for k, v in raw.items() if k in allowed}


def load_config(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH
    if not path.exists():
        return Config()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    watch_raw = dict(raw.get("watch", {}))
    rules_raw = watch_raw.pop("rules", None)
    watch = WatchConfig(**_known_fields(WatchConfig, watch_raw, "watch"))
    if rules_raw is not None:
        if not isinstance(rules_raw, list) or not rules_raw:
            raise ValueError("config.toml: [[watch.rules]] 至少要有一条")
        watch.rules = [
            Rule(**_known_fields(Rule, r, "watch.rules")) for r in rules_raw
        ]

    cfg = Config(
        watch=watch,
        notify=NotifyConfig(**_known_fields(NotifyConfig, raw.get("notify", {}), "notify")),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    from . import slots  # 避免循环导入

    w = cfg.watch
    if not w.menus:
        raise ValueError("config.toml: [watch].menus 不能为空")
    if w.horizon_days < 1:
        raise ValueError("config.toml: [watch].horizon_days 至少是 1")
    if not w.rules:
        raise ValueError("config.toml: [[watch.rules]] 至少要有一条")
    for rule in w.rules:
        if not 0 <= rule.hour_from < rule.hour_to <= 24:
            raise ValueError(
                f"config.toml: 规则「{rule.describe()}」需要 "
                f"0 <= hour_from < hour_to <= 24，当前是 "
                f"{rule.hour_from} / {rule.hour_to}"
            )
        # 星期拼错在这里就炸掉，而不是跑到云端才发现筛出来永远是空
        slots.weekday_mask(rule.weekdays)


def load_dotenv(path: Path | None = None) -> None:
    """把 .env 读进 os.environ。已存在的环境变量优先，方便 CI 覆盖。"""
    path = path or ENV_PATH
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
