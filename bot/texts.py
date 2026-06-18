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
    "• «Купить / продлить» — выбрать тариф и оплатить\n"
    "• «Моя подписка» — статус, трафик и данные для подключения.\n"
    "• После оплаты доступ выдаётся автоматически.\n"
    "Если возникли проблемы — напишите "
    '<a href="https://t.me/Sergey_Kyzmich">администратору</a>.\n\n'
    "<b>Инструкция по подключению:</b>\n\n"
    "Скачать приложение (любое, которое доступно)\n"
    "<b>iOS:</b> "
    '<a href="https://apps.apple.com/us/app/v2raytun/id6476628951">v2raytun</a>, '
    '<a href="https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690">v2box</a>, '
    '<a href="https://apps.apple.com/us/app/super-v2ray-tunnel-2026/id6755873784">super-v2ray-tunnel-2026</a>\n'
    "<b>Android:</b> "
    '<a href="https://play.google.com/store/apps/details?id=com.v2raytun.android">v2raytun</a>, '
    '<a href="https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box">v2box</a>\n'
    "<b>Windows:</b> "
    '<a href="https://github.com/mdf45/v2raytun/releases">v2raytun</a>\n\n'
    "<b>В боте:</b>\n"
    "1. Нажимаем 💳 Купить / продлить\n"
    "2. Выбираем желанный период и оплачиваем удобным способом\n"
    '3. После оплаты нажимаем «✅ Я оплатил — проверить»\n'
    "4. После чего бот пришлёт 2 ссылки. Копируем 2-ю (большую)\n\n"
    "<b>В приложении VPN:</b>\n"
    '1. В правом верхнем углу нажимаем «+»\n'
    '2. Нажимаем «Вставить из буфера обмена» или «Ручной ввод» и вставляем ссылку\n'
    "3. ✅ Нажимаем подключиться и пользуемся VPN\n"
    "(в первый раз нужно будет принять все запросы на доступ)"
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
