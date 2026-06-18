"""User-facing command and callback handlers."""

from __future__ import annotations

import logging

from telebot import types

from . import db, keyboards, payments, provisioning, texts
from .config import CONFIG
from .core import bot, xui
from .links import make_qr

log = logging.getLogger("handlers.user")


def _register_user(message: types.Message) -> bool:
    user = message.from_user
    db.upsert_user(user.id, user.username, user.first_name)
    rec = db.get_user(user.id)
    return bool(rec and rec.get("is_blocked"))


def send_main_menu(chat_id: int, tg_id: int, text: str) -> None:
    bot.send_message(chat_id, text, reply_markup=keyboards.main_menu(CONFIG.is_admin(tg_id)))


@bot.message_handler(commands=["start"])
def cmd_start(message: types.Message) -> None:
    blocked = _register_user(message)
    if blocked:
        bot.send_message(message.chat.id, "🚫 Ваш доступ к боту ограничён.")
        return
    name = message.from_user.first_name or "друг"
    is_admin = CONFIG.is_admin(message.from_user.id)
    text = (texts.WELCOME_ADMIN if is_admin else texts.WELCOME).format(name=name)
    send_main_menu(message.chat.id, message.from_user.id, text)


@bot.message_handler(commands=["help"])
def cmd_help(message: types.Message) -> None:
    bot.send_message(message.chat.id, texts.HELP)


@bot.message_handler(commands=["id"])
def cmd_id(message: types.Message) -> None:
    bot.reply_to(message, f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@bot.message_handler(func=lambda m: m.text == "💳 Купить / продлить")
def menu_buy(message: types.Message) -> None:
    _register_user(message)
    bot.send_message(message.chat.id, texts.plans_text(), reply_markup=keyboards.plans_keyboard())


@bot.message_handler(func=lambda m: m.text == "ℹ️ Помощь")
def menu_help(message: types.Message) -> None:
    bot.send_message(message.chat.id, texts.HELP)


@bot.message_handler(func=lambda m: m.text == "👤 Моя подписка")
def menu_my_sub(message: types.Message) -> None:
    _show_subscription(message.chat.id, message.from_user.id)


def _show_subscription(chat_id: int, tg_id: int) -> None:
    sub = db.get_subscription(tg_id)
    if not sub:
        bot.send_message(
            chat_id,
            "У вас пока нет активной подписки. Нажмите «💳 Купить / продлить».",
            reply_markup=keyboards.main_menu(CONFIG.is_admin(tg_id)),
        )
        return
    sub_url, direct = provisioning.connection_links(sub)
    traffic = None
    try:
        traffic = xui.get_client_traffic(sub["email"])
    except Exception:
        pass
    text = texts.connection_message(sub, sub_url, direct, traffic)
    bot.send_message(chat_id, text, reply_markup=keyboards.my_sub_keyboard(sub["sub_id"]))


# ----------------------------------------------------------- buy / payment
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("buy:"))
def cb_buy(call: types.CallbackQuery) -> None:
    plan_key = call.data.split(":", 1)[1]
    plan = CONFIG.plans.get(plan_key)
    if not plan:
        bot.answer_callback_query(call.id, "Тариф не найден")
        return

    label = payments.new_label(call.from_user.id)
    description = f"VPN {texts.plan_title(plan_key)}"
    try:
        external_id, url = payments.create_yookassa_payment(
            label=label,
            tg_id=call.from_user.id,
            plan_key=plan_key,
            amount=plan.price,
            description=description,
        )
    except Exception as exc:
        log.exception("Failed to create YooKassa payment")
        bot.answer_callback_query(call.id, "Ошибка создания платежа", show_alert=True)
        bot.send_message(call.message.chat.id, f"⚠️ Не удалось создать платёж: {exc}")
        return

    db.create_payment(call.from_user.id, label, plan_key, plan.price, external_id)
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        (
            f"🧾 Тариф: <b>{texts.plan_title(plan_key)}</b>\n"
            f"💰 Сумма: <b>{plan.price:g} {CONFIG.currency}</b>\n\n"
            "1) Нажмите «💳 Оплатить» и завершите оплату.\n"
            "2) Вернитесь и нажмите «✅ Я оплатил — проверить».\n\n"
            "Доступ выдаётся автоматически после подтверждения оплаты."
        ),
        reply_markup=keyboards.pay_keyboard(url, label),
    )


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("check:"))
def cb_check(call: types.CallbackQuery) -> None:
    label = call.data.split(":", 1)[1]
    payment = db.get_payment_by_label(label)
    if not payment:
        bot.answer_callback_query(call.id, "Платёж не найден", show_alert=True)
        return
    if payment["status"] == "success":
        bot.answer_callback_query(call.id, "Этот платёж уже подтверждён")
        _show_subscription(call.message.chat.id, call.from_user.id)
        return

    bot.answer_callback_query(call.id, "Проверяем оплату…")
    external_id = payment.get("external_id") or ""
    if payments.is_payment_succeeded(external_id):
        finalize_payment(label)
    else:
        bot.send_message(
            call.message.chat.id,
            "❌ Оплата пока не найдена. Если вы только что оплатили, подождите "
            "минуту и нажмите кнопку проверки ещё раз.",
        )


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("cancelpay:"))
def cb_cancel_pay(call: types.CallbackQuery) -> None:
    label = call.data.split(":", 1)[1]
    payment = db.get_payment_by_label(label)
    if payment and payment["status"] == "pending":
        db.mark_payment(label, "cancelled")
    bot.answer_callback_query(call.id, "Платёж отменён")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass


def finalize_payment(label: str) -> bool:
    """Provision the subscription for a confirmed payment. Idempotent."""
    payment = db.get_payment_by_label(label)
    if not payment or payment["status"] == "success":
        return False
    plan = CONFIG.plans.get(payment["plan"])
    if not plan:
        log.error("Plan %s for payment %s no longer exists", payment["plan"], label)
        return False

    tg_id = payment["tg_id"]
    try:
        sub = provisioning.create_or_renew(tg_id, plan)
    except Exception as exc:
        log.exception("Provisioning failed for %s", tg_id)
        bot.send_message(tg_id, f"⚠️ Оплата получена, но при выдаче доступа произошла ошибка: {exc}\n"
                                "Свяжитесь с администратором.")
        return False

    db.mark_payment(label, "success")
    sub_url, direct = provisioning.connection_links(sub)
    traffic = None
    try:
        traffic = xui.get_client_traffic(sub["email"])
    except Exception:
        pass
    bot.send_message(tg_id, "🎉 Оплата подтверждена! Спасибо.")
    bot.send_message(
        tg_id,
        texts.connection_message(sub, sub_url, direct, traffic),
        reply_markup=keyboards.my_sub_keyboard(sub["sub_id"]),
    )
    if sub_url:
        try:
            bot.send_photo(tg_id, make_qr(sub_url), caption="📷 QR-код вашей подписки")
        except Exception:
            pass
    return True


# --------------------------------------------------------------- my sub cb
@bot.callback_query_handler(func=lambda c: c.data == "myrefresh")
def cb_my_refresh(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id, "Обновлено")
    _show_subscription(call.message.chat.id, call.from_user.id)


@bot.callback_query_handler(func=lambda c: c.data == "renew")
def cb_renew(call: types.CallbackQuery) -> None:
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, texts.plans_text(), reply_markup=keyboards.plans_keyboard())


@bot.callback_query_handler(func=lambda c: c.data == "myqr")
def cb_my_qr(call: types.CallbackQuery) -> None:
    sub = db.get_subscription(call.from_user.id)
    if not sub:
        bot.answer_callback_query(call.id, "Нет подписки", show_alert=True)
        return
    sub_url, direct = provisioning.connection_links(sub)
    target = sub_url or direct
    if not target:
        bot.answer_callback_query(call.id, "Нет ссылки", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    bot.send_photo(call.message.chat.id, make_qr(target), caption="📷 QR-код подключения")
