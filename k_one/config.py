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
class WatchConfig:
    menus: list[str] = field(default_factory=lambda: ["s0000A5844"])
    horizon_days: int = 28
    weekdays: list[str] = field(default_factory=lambda: ["sat", "sun"])
    hour_from: int = 10
    hour_to: int = 18
    include_few_left: bool = True


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
    cfg = Config(
        watch=WatchConfig(**_known_fields(WatchConfig, raw.get("watch", {}), "watch")),
        notify=NotifyConfig(**_known_fields(NotifyConfig, raw.get("notify", {}), "notify")),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    w = cfg.watch
    if not w.menus:
        raise ValueError("config.toml: [watch].menus 不能为空")
    if w.horizon_days < 1:
        raise ValueError("config.toml: [watch].horizon_days 至少是 1")
    if not 0 <= w.hour_from < w.hour_to <= 24:
        raise ValueError(
            f"config.toml: 需要 0 <= hour_from < hour_to <= 24，"
            f"当前是 {w.hour_from} / {w.hour_to}"
        )
    # weekdays 拼写错误在这里就炸掉，而不是跑到云端才发现过滤全空
    from . import slots

    slots.weekday_mask(w.weekdays)


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
