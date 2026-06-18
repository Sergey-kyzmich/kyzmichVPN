"""User-facing text strings (Russian) and formatting helpers."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from .config import CONFIG

GB = 1024 * 1024 * 1024


def fmt_bytes(n: int) -> str:
    if not n:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.2f} {units[i]}"


def fmt_expiry(expiry_ms: int) -> str:
    if not expiry_ms:
        return "∞ (бессрочно)"
    secs = expiry_ms / 1000
    if secs < time.time():
        return "истёк"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(secs))


def fmt_remaining(expiry_ms: int) -> str:
    if not expiry_ms:
        return "бессрочно"
    diff = expiry_ms / 1000 - time.time()
    if diff <= 0:
        return "истёк"
    days = int(diff // 86400)
    hours = int((diff % 86400) // 3600)
    if days > 0:
        return f"{days} дн. {hours} ч."
    return f"{hours} ч."


WELCOME = (
    "👋 Привет, {name}!\n\n"
    "Это бот для подключения к VPN. Оформи подписку — и получишь данные "
    "для подключения автоматически.\n\n"
    "Выбери действие в меню ниже."
)

WELCOME_ADMIN = WELCOME + "\n\n🛠 Тебе доступна админ-панель: /admin"

HELP = (
    "ℹ️ <b>Помощь</b>\n\n"
    "• «Купить / продлить» — выбрать тариф и оплатить через ЮKassa.\n"
    "• «Моя подписка» — статус, трафик и данные для подключения.\n"
    "• После оплаты доступ выдаётся автоматически.\n\n"
    "Если возникли проблемы — напишите администратору."
)


def plans_text() -> str:
    lines = ["💳 <b>Выберите тариф:</b>\n"]
    for plan in CONFIG.plans.values():
        gb = "безлимит" if plan.gb == 0 else f"{plan.gb} ГБ"
        lines.append(f"• {plan_title(plan.key)} — {plan.price:g} {CONFIG.currency} ({gb})")
    return "\n".join(lines)


def plan_title(key: str) -> str:
    plan = CONFIG.plans.get(key)
    if not plan:
        return key
    months = plan.days // 30
    if months >= 1 and plan.days % 30 == 0:
        return f"{months} мес."
    return f"{plan.days} дн."


def connection_message(sub: Dict[str, Any], sub_url: str, direct: Optional[str],
                       traffic: Optional[Dict[str, Any]] = None) -> str:
    lines = ["✅ <b>Ваша подписка активна!</b>\n"]
    lines.append(f"📅 Действует до: <b>{fmt_expiry(sub['expiry_time'])}</b>")
    lines.append(f"⏳ Осталось: <b>{fmt_remaining(sub['expiry_time'])}</b>")
    if traffic:
        used = (traffic.get("up", 0) or 0) + (traffic.get("down", 0) or 0)
        total = traffic.get("total", 0) or 0
        total_str = "∞" if total == 0 else fmt_bytes(total)
        lines.append(f"📊 Трафик: <b>{fmt_bytes(used)}</b> / {total_str}")
    lines.append("")
    if sub_url:
        lines.append("🔗 <b>Ссылка-подписка</b> (вставьте в v2rayNG / Hiddify / Streisand):")
        lines.append(f"<code>{sub_url}</code>")
    if direct:
        lines.append("")
        lines.append("🔑 <b>Прямая ссылка для подключения:</b>")
        lines.append(f"<code>{direct}</code>")
    return "\n".join(lines)
