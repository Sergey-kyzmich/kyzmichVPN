"""Inline and reply keyboards."""

from __future__ import annotations

from typing import Any, Dict, List

from telebot import types

from .config import CONFIG
from .texts import plan_title


def main_menu(is_admin: bool = False) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("💳 Купить / продлить")
    kb.row("👤 Моя подписка", "ℹ️ Помощь")
    if is_admin:
        kb.row("🛠 Админ-панель")
    return kb


def plans_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    for plan in CONFIG.plans.values():
        kb.add(
            types.InlineKeyboardButton(
                f"{plan_title(plan.key)} — {plan.price:g} {CONFIG.currency}",
                callback_data=f"buy:{plan.key}",
            )
        )
    return kb


def pay_keyboard(url: str, label: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💳 Оплатить", url=url))
    kb.add(types.InlineKeyboardButton("✅ Я оплатил — проверить", callback_data=f"check:{label}"))
    kb.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancelpay:{label}"))
    return kb


def my_sub_keyboard(sub_id: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📷 QR-код", callback_data="myqr"))
    kb.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="myrefresh"))
    kb.add(types.InlineKeyboardButton("➕ Продлить", callback_data="renew"))
    return kb


# ------------------------------------------------------------------- admin
def admin_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📊 Статистика", callback_data="a:stats"))
    kb.add(types.InlineKeyboardButton("👥 Пользователи", callback_data="a:users:0"))
    kb.add(types.InlineKeyboardButton("📡 Инбаунды", callback_data="a:inbounds"))
    kb.add(types.InlineKeyboardButton("📣 Рассылка всем", callback_data="a:broadcast"))
    kb.add(types.InlineKeyboardButton("🚚 Перенести всех на новое подключение", callback_data="a:migrate"))
    return kb


def users_list_keyboard(subs: List[Dict[str, Any]], page: int, per_page: int,
                        total: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    for sub in subs:
        label = f"{sub['tg_id']} · {sub['email']}"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"a:user:{sub['tg_id']}"))
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"a:users:{page - 1}"))
    if (page + 1) * per_page < total:
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"a:users:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.add(types.InlineKeyboardButton("⬅️ В меню", callback_data="a:menu"))
    return kb


def user_admin_keyboard(tg_id: int, enabled: bool) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    if enabled:
        kb.add(types.InlineKeyboardButton("⛔ Отключить", callback_data=f"a:disable:{tg_id}"))
    else:
        kb.add(types.InlineKeyboardButton("✅ Включить", callback_data=f"a:enable:{tg_id}"))
    kb.row(
        types.InlineKeyboardButton("+30 дн.", callback_data=f"a:extend:{tg_id}:30"),
        types.InlineKeyboardButton("+90 дн.", callback_data=f"a:extend:{tg_id}:90"),
    )
    kb.add(types.InlineKeyboardButton("♻️ Сбросить трафик", callback_data=f"a:reset:{tg_id}"))
    kb.add(types.InlineKeyboardButton("🔗 Ссылки подключения", callback_data=f"a:links:{tg_id}"))
    kb.add(types.InlineKeyboardButton("✉️ Написать", callback_data=f"a:msg:{tg_id}"))
    kb.add(types.InlineKeyboardButton("🗑 Удалить", callback_data=f"a:del:{tg_id}"))
    kb.add(types.InlineKeyboardButton("⬅️ К списку", callback_data="a:users:0"))
    return kb


def confirm_keyboard(yes_cb: str, no_cb: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ Да", callback_data=yes_cb),
        types.InlineKeyboardButton("❌ Нет", callback_data=no_cb),
    )
    return kb


def inbounds_keyboard(inbounds: List[Dict[str, Any]], action: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    for ib in inbounds:
        title = f"#{ib.get('id')} {ib.get('remark', '')} ({ib.get('protocol', '')})"
        kb.add(types.InlineKeyboardButton(title, callback_data=f"{action}:{ib.get('id')}"))
    kb.add(types.InlineKeyboardButton("⬅️ В меню", callback_data="a:menu"))
    return kb
