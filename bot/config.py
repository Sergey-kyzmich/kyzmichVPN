"""Configuration loader for the kyzmichVPN bot.

Reads settings from ``config.ini`` (see ``config.example.ini`` for the
template). All access goes through the module-level ``CONFIG`` singleton.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from typing import Dict, List

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.ini"
)


def _resolve_config_path() -> str:
    """Absolute path to config.ini (project root by default)."""
    env_path = os.environ.get("KYZMICH_CONFIG", "").strip()
    if env_path:
        return os.path.abspath(env_path)
    return _DEFAULT_CONFIG_PATH


CONFIG_PATH = _resolve_config_path()


@dataclass
class Plan:
    key: str
    days: int
    price: float
    gb: int  # 0 = unlimited

    @property
    def total_bytes(self) -> int:
        return self.gb * 1024 * 1024 * 1024 if self.gb > 0 else 0


@dataclass
class Config:
    # telegram
    token: str
    admins: List[int]
    proxy: str
    # xui
    xui_base_url: str
    xui_username: str
    xui_password: str
    inbound_id: int
    flow: str
    sub_base_url: str
    # yookassa
    yookassa_shop_id: str
    yookassa_secret_key: str
    yookassa_return_url: str
    # subscription
    default_gb: int
    limit_ip: int
    currency: str
    plans: Dict[str, Plan] = field(default_factory=dict)

    def is_admin(self, tg_id: int) -> bool:
        return tg_id in self.admins


def _split_ids(raw: str) -> List[int]:
    ids: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return ids


def _parse_plans(parser: configparser.ConfigParser) -> Dict[str, Plan]:
    plans: Dict[str, Plan] = {}
    if not parser.has_section("plans"):
        return plans
    for key, raw in parser.items("plans"):
        chunks = raw.split(":")
        if len(chunks) < 2:
            continue
        try:
            days = int(chunks[0])
            price = float(chunks[1])
            gb = int(chunks[2]) if len(chunks) > 2 and chunks[2].strip() else 0
        except ValueError:
            continue
        plans[key] = Plan(key=key, days=days, price=price, gb=gb)
    return plans


def load_config(path: str | None = None) -> Config:
    if path is None:
        path = _resolve_config_path()
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Config file not found at {path}. Copy config.example.ini to config.ini "
            f"and fill in your values."
        )

    parser = configparser.ConfigParser()
    # utf-8-sig tolerates a BOM, which Windows editors (Notepad/PowerShell)
    # often add and which would otherwise break the parser.
    parser.read(path, encoding="utf-8-sig")

    cfg = Config(
        token=parser.get("telegram", "token", fallback="").strip(),
        admins=_split_ids(parser.get("telegram", "admins", fallback="")),
        proxy=parser.get("telegram", "proxy", fallback="").strip(),
        xui_base_url=parser.get("xui", "base_url", fallback="").strip().rstrip("/"),
        xui_username=parser.get("xui", "username", fallback="").strip(),
        xui_password=parser.get("xui", "password", fallback="").strip(),
        inbound_id=parser.getint("xui", "inbound_id", fallback=1),
        flow=parser.get("xui", "flow", fallback="").strip(),
        sub_base_url=parser.get("xui", "sub_base_url", fallback="").strip().rstrip("/"),
        yookassa_shop_id=parser.get("yookassa", "shop_id", fallback="").strip(),
        yookassa_secret_key=parser.get("yookassa", "secret_key", fallback="").strip(),
        yookassa_return_url=parser.get("yookassa", "return_url", fallback="https://t.me/").strip(),
        default_gb=parser.getint("subscription", "default_gb", fallback=0),
        limit_ip=parser.getint("subscription", "limit_ip", fallback=0),
        currency=parser.get("subscription", "currency", fallback="RUB").strip(),
        plans=_parse_plans(parser),
    )

    if not cfg.token:
        raise ValueError("telegram.token is empty in config.ini")
    if not cfg.xui_base_url:
        raise ValueError("xui.base_url is empty in config.ini")
    if not cfg.plans:
        raise ValueError("No [plans] defined in config.ini")

    return cfg


def config_source_hint() -> str:
    """Human-readable hint about which config file is active."""
    if os.environ.get("KYZMICH_CONFIG"):
        return f"{CONFIG_PATH} (через переменную KYZMICH_CONFIG)"
    return CONFIG_PATH


def reload_config() -> Config:
    """Re-read config.ini from disk (picks up edits without bot restart)."""
    global CONFIG
    CONFIG = load_config()
    return CONFIG


CONFIG: Config = load_config()
