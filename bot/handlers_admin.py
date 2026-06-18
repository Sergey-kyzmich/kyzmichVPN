"""Admin command and callback handlers: full user management, broadcast and
bulk migration of all users to a new connection/inbound with notifications.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict

from telebot import types

from . import db, keyboards, provisioning, texts
from .config import CONFIG
from .core import bot, xui

log = logging.getLogger("handlers.admin")

USERS_PER_PAGE = 8

# In-memory admin input states: {admin_tg_id: {"action": str, ...}}
admin_states: Dict[int, Dict[str, Any]] = {}


def _is_admin(tg_id: int) -> bool:
    return CONFIG.is_admin(tg_id)


def _show_admin_menu(chat_id: int) -> None:
    bot.send_message(chat_id, "🛠 <b>Админ-панель</b>", reply_markup=keyboards.admin_menu())


@bot.message_handler(commands=["admin"])
def cmd_admin(message: types.Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    _show_admin_menu(message.chat.id)


@bot.message_handler(func=lambda m: m.text == "🛠 Админ-панель")
def menu_admin(message: types.Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    _show_admin_menu(message.chat.id)


# ----------------------------------------------------------------- routing
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("a:"))
def admin_router(call: types.CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return

    parts = call.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
        if action == "menu":
            bot.answer_callback_query(call.id)
            _edit_menu(call)
        elif action == "stats":
            _show_stats(call)
        elif action == "users":
            _list_users(call, int(parts[2]))
        elif action == "user":
            _show_user(call, int(parts[2]))
        elif action == "disable":
            _toggle_user(call, int(parts[2]), enable=False)
        elif action == "enable":
            _toggle_user(call, int(parts[2]), enable=True)
        elif action == "extend":
            _extend_user(call, int(parts[2]), int(parts[3]))
        elif action == "reset":
            _reset_user(call, int(parts[2]))
        elif action == "links":
            _user_links(call, int(parts[2]))
        elif action == "del":
            _confirm_delete(call, int(parts[2]))
        elif action == "delgo":
            _delete_user(call, int(parts[2]))
        elif action == "msg":
            _prompt_message(call, int(parts[2]))
        elif action == "inbounds":
            _show_inbounds(call)
        elif action == "broadcast":
            _prompt_broadcast(call)
        elif action == "migrate":
            _migrate_choose(call)
        elif action == "migto":
            _migrate_confirm(call, int(parts[2]))
        elif action == "miggo":
            _migrate_go(call, int(parts[2]))
        else:
            bot.answer_callback_query(call.id, "Неизвестное действие")
    except Exception as exc:
        log.exception("Admin action failed")
        bot.answer_callback_query(call.id, "Ошибка")
        bot.send_message(call.message.chat.id, f"⚠️ Ошибка: {exc}")


# ------------------------------------------------------------------- views
def _edit_menu(call: types.CallbackQuery) -> None:
    try:
        bot.edit_message_text("🛠 <b>Админ-панель</b>", call.message.chat.id,
                              call.message.message_id, reply_markup=keyboards.admin_menu())
    except Exception:
        _show_admin_menu(call.message.chat.id)


def _show_stats(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id)
    total_users = db.count_users()
    subs = db.all_subscriptions()
    active = db.active_subscriptions()
    rev = db.revenue()
    online = []
    try:
        online = xui.online_clients()
    except Exception:
        pass
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"🔑 Подписок всего: <b>{len(subs)}</b>\n"
        f"✅ Активных: <b>{len(active)}</b>\n"
        f"🟢 Онлайн сейчас: <b>{len(online)}</b>\n"
        f"💰 Выручка: <b>{rev:g} {CONFIG.currency}</b>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ В меню", callback_data="a:menu"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)


def _list_users(call: types.CallbackQuery, page: int) -> None:
    bot.answer_callback_query(call.id)
    subs = db.all_subscriptions()
    total = len(subs)
    start = page * USERS_PER_PAGE
    chunk = subs[start:start + USERS_PER_PAGE]
    if not chunk and page == 0:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ В меню", callback_data="a:menu"))
        bot.edit_message_text("Пока нет ни одной подписки.", call.message.chat.id,
                              call.message.message_id, reply_markup=kb)
        return
    kb = keyboards.users_list_keyboard(chunk, page, USERS_PER_PAGE, total)
    bot.edit_message_text(
        f"👥 <b>Пользователи</b> ({total}) — стр. {page + 1}",
        call.message.chat.id, call.message.message_id, reply_markup=kb,
    )


def _user_detail_text(tg_id: int) -> str:
    user = db.get_user(tg_id)
    sub = db.get_subscription(tg_id)
    lines = [f"👤 <b>Пользователь</b> <code>{tg_id}</code>"]
    if user:
        uname = f"@{user['username']}" if user.get("username") else "—"
        lines.append(f"Имя: {user.get('first_name') or '—'}  ({uname})")
        lines.append(f"Заблокирован: {'да' if user.get('is_blocked') else 'нет'}")
    if not sub:
        lines.append("\nПодписки нет.")
        return "\n".join(lines)
    lines.append(f"\n📧 Email: <code>{sub['email']}</code>")
    lines.append(f"🆔 subId: <code>{sub['sub_id']}</code>")
    lines.append(f"📡 Inbound: #{sub['inbound_id']}")
    lines.append(f"📅 До: {texts.fmt_expiry(sub['expiry_time'])} ({texts.fmt_remaining(sub['expiry_time'])})")
    lines.append(f"⚙️ Активен: {'да' if sub['enable'] else 'нет'}")
    try:
        traffic = xui.get_client_traffic(sub["email"])
        if traffic:
            used = (traffic.get("up", 0) or 0) + (traffic.get("down", 0) or 0)
            total = traffic.get("total", 0) or 0
            total_str = "∞" if total == 0 else texts.fmt_bytes(total)
            lines.append(f"📊 Трафик: {texts.fmt_bytes(used)} / {total_str}")
    except Exception:
        pass
    pays = db.payments_of_user(tg_id, limit=5)
    if pays:
        lines.append("\n🧾 Последние платежи:")
        for p in pays:
            ts = time.strftime("%Y-%m-%d", time.localtime(p["created_at"] / 1000))
            lines.append(f"  • {ts} — {p['amount']:g} {CONFIG.currency} — {p['status']}")
    return "\n".join(lines)


def _show_user(call: types.CallbackQuery, tg_id: int) -> None:
    bot.answer_callback_query(call.id)
    sub = db.get_subscription(tg_id)
    enabled = bool(sub and sub["enable"])
    bot.edit_message_text(
        _user_detail_text(tg_id), call.message.chat.id, call.message.message_id,
        reply_markup=keyboards.user_admin_keyboard(tg_id, enabled),
    )


def _toggle_user(call: types.CallbackQuery, tg_id: int, enable: bool) -> None:
    sub = db.get_subscription(tg_id)
    if not sub:
        bot.answer_callback_query(call.id, "Нет подписки", show_alert=True)
        return
    provisioning.set_enabled(sub, enable)
    bot.answer_callback_query(call.id, "Включён" if enable else "Отключён")
    _show_user(call, tg_id)
    try:
        bot.send_message(tg_id, "✅ Ваш доступ к VPN включён." if enable
                         else "⛔ Ваш доступ к VPN временно отключён.")
    except Exception:
        pass


def _extend_user(call: types.CallbackQuery, tg_id: int, days: int) -> None:
    sub = db.get_subscription(tg_id)
    if not sub:
        bot.answer_callback_query(call.id, "Нет подписки", show_alert=True)
        return
    new_expiry = provisioning.extend_days(sub, days)
    bot.answer_callback_query(call.id, f"Продлено на {days} дн.")
    _show_user(call, tg_id)
    try:
        bot.send_message(tg_id, f"➕ Ваша подписка продлена на {days} дн. "
                                f"Действует до {texts.fmt_expiry(new_expiry)}.")
    except Exception:
        pass


def _reset_user(call: types.CallbackQuery, tg_id: int) -> None:
    sub = db.get_subscription(tg_id)
    if not sub:
        bot.answer_callback_query(call.id, "Нет подписки", show_alert=True)
        return
    provisioning.reset_traffic(sub)
    bot.answer_callback_query(call.id, "Трафик сброшен")
    _show_user(call, tg_id)


def _user_links(call: types.CallbackQuery, tg_id: int) -> None:
    sub = db.get_subscription(tg_id)
    if not sub:
        bot.answer_callback_query(call.id, "Нет подписки", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    sub_url, direct = provisioning.connection_links(sub)
    msg = "🔗 Ссылки подключения:\n"
    if sub_url:
        msg += f"\nSub: <code>{sub_url}</code>"
    if direct:
        msg += f"\n\nDirect: <code>{direct}</code>"
    bot.send_message(call.message.chat.id, msg)


def _confirm_delete(call: types.CallbackQuery, tg_id: int) -> None:
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"🗑 Удалить клиента пользователя <code>{tg_id}</code> из панели и БД?",
        call.message.chat.id, call.message.message_id,
        reply_markup=keyboards.confirm_keyboard(f"a:delgo:{tg_id}", f"a:user:{tg_id}"),
    )


def _delete_user(call: types.CallbackQuery, tg_id: int) -> None:
    sub = db.get_subscription(tg_id)
    if sub:
        provisioning.delete_client(sub)
    bot.answer_callback_query(call.id, "Удалено")
    _list_users(call, 0)
    try:
        bot.send_message(tg_id, "❌ Ваша подписка была удалена администратором.")
    except Exception:
        pass


def _prompt_message(call: types.CallbackQuery, tg_id: int) -> None:
    admin_states[call.from_user.id] = {"action": "msg", "target": tg_id}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id,
                     f"✉️ Отправьте текст сообщения для пользователя <code>{tg_id}</code> "
                     "(или /cancel для отмены).")


def _show_inbounds(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id)
    inbounds = xui.list_inbounds()
    lines = ["📡 <b>Инбаунды панели:</b>\n"]
    for ib in inbounds:
        flag = "⭐" if ib.get("id") == CONFIG.inbound_id else "•"
        lines.append(f"{flag} #{ib.get('id')} {ib.get('remark', '')} "
                     f"({ib.get('protocol', '')}, порт {ib.get('port', '?')})")
    lines.append(f"\n⭐ — инбаунд для новых клиентов (config.ini: inbound_id={CONFIG.inbound_id})")
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ В меню", callback_data="a:menu"))
    bot.edit_message_text("\n".join(lines), call.message.chat.id,
                          call.message.message_id, reply_markup=kb)


# --------------------------------------------------------------- broadcast
def _prompt_broadcast(call: types.CallbackQuery) -> None:
    admin_states[call.from_user.id] = {"action": "broadcast"}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id,
                     "📣 Отправьте сообщение для рассылки всем пользователям "
                     "(или /cancel для отмены).")


# ----------------------------------------------------------- migrate flow
def _migrate_choose(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id)
    inbounds = xui.list_inbounds()
    bot.edit_message_text(
        "🚚 Выберите инбаунд (новое подключение), на который перенести "
        "<b>всех</b> активных пользователей:",
        call.message.chat.id, call.message.message_id,
        reply_markup=keyboards.inbounds_keyboard(inbounds, "a:migto"),
    )


def _migrate_confirm(call: types.CallbackQuery, inbound_id: int) -> None:
    bot.answer_callback_query(call.id)
    active = db.active_subscriptions()
    bot.edit_message_text(
        f"⚠️ Перенести <b>{len(active)}</b> активных пользователей на инбаунд "
        f"#{inbound_id} и уведомить каждого новыми данными подключения?\n\n"
        "Старый клиент будет удалён со старого инбаунда.",
        call.message.chat.id, call.message.message_id,
        reply_markup=keyboards.confirm_keyboard(f"a:miggo:{inbound_id}", "a:menu"),
    )


def _migrate_go(call: types.CallbackQuery, inbound_id: int) -> None:
    bot.answer_callback_query(call.id, "Запускаю перенос…")
    admin_chat = call.message.chat.id
    bot.edit_message_text("🚚 Перенос запущен, это может занять время…",
                          admin_chat, call.message.message_id)
    threading.Thread(target=_run_migration, args=(admin_chat, inbound_id), daemon=True).start()


def _run_migration(admin_chat: int, inbound_id: int) -> None:
    active = db.active_subscriptions()
    ok, failed = 0, 0
    for sub in active:
        try:
            new_sub = provisioning.migrate_to_inbound(sub, inbound_id)
            sub_url, direct = provisioning.connection_links(new_sub)
            try:
                bot.send_message(
                    sub["tg_id"],
                    "🔔 <b>Сервер обновлён!</b> Ваши данные для подключения изменились.\n\n"
                    + texts.connection_message(new_sub, sub_url, direct),
                    reply_markup=keyboards.my_sub_keyboard(new_sub["sub_id"]),
                )
            except Exception:
                pass  # user may have blocked the bot
            ok += 1
            time.sleep(0.1)
        except Exception as exc:
            failed += 1
            log.warning("Migration failed for %s: %s", sub.get("tg_id"), exc)
    bot.send_message(admin_chat,
                     f"✅ Перенос завершён.\nУспешно: {ok}\nОшибок: {failed}",
                     reply_markup=keyboards.admin_menu())


# -------------------------------------------------- admin text input state
@bot.message_handler(commands=["cancel"])
def cmd_cancel(message: types.Message) -> None:
    if admin_states.pop(message.from_user.id, None):
        bot.send_message(message.chat.id, "Отменено.",
                         reply_markup=keyboards.main_menu(_is_admin(message.from_user.id)))


@bot.message_handler(func=lambda m: m.from_user.id in admin_states, content_types=["text"])
def handle_admin_state(message: types.Message) -> None:
    state = admin_states.get(message.from_user.id)
    if not state:
        return
    action = state.get("action")

    if action == "msg":
        target = state["target"]
        admin_states.pop(message.from_user.id, None)
        try:
            bot.send_message(target, f"✉️ Сообщение от администратора:\n\n{message.text}")
            bot.send_message(message.chat.id, "✅ Отправлено.")
        except Exception as exc:
            bot.send_message(message.chat.id, f"⚠️ Не удалось отправить: {exc}")

    elif action == "broadcast":
        admin_states.pop(message.from_user.id, None)
        threading.Thread(target=_run_broadcast, args=(message.chat.id, message.text),
                         daemon=True).start()


def _run_broadcast(admin_chat: int, text: str) -> None:
    users = db.all_users()
    ok, failed = 0, 0
    for user in users:
        try:
            bot.send_message(user["tg_id"], f"📣 {text}")
            ok += 1
            time.sleep(0.05)
        except Exception:
            failed += 1
    bot.send_message(admin_chat, f"📣 Рассылка завершена.\nДоставлено: {ok}\nОшибок: {failed}",
                     reply_markup=keyboards.admin_menu())
