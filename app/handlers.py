from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler
from . import db, payments
from .config import cfg


def start(update, context):
    update.message.reply_text("Привет! Используй /plans чтобы увидеть доступные тарифы.")


def plans_cmd(update, context):
    plans = db.list_plans()
    if not plans:
        update.message.reply_text("Тарифы пока не добавлены. Админ может добавить через /addplan")
        return
    kb = [[InlineKeyboardButton(f"{p['name']} — {p['days']}d — {p['price']}", callback_data=f"buy:{p['id']}")] for p in plans]
    update.message.reply_text("Выберите тариф:", reply_markup=InlineKeyboardMarkup(kb))


def buy_callback(update, context):
    query = update.callback_query
    query.answer()
    data = query.data
    if not data or not data.startswith("buy:"):
        return
    plan_id = int(data.split(":", 1)[1])
    plan = db.get_plan_by_id(plan_id)
    if not plan:
        query.edit_message_text("Тариф не найден.")
        return
    user = query.from_user
    payment_ref, pay_link = payments.create_payment(user.id, user.username or str(user.id), plan)
    kb = [[InlineKeyboardButton("Я оплатил", callback_data=f"checkpay:{payment_ref}")]]
    text = f"Чтобы оформить {plan['name']} ({plan['price']}), оплатите по ссылке:\n{pay_link}"
    query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


def checkpay_callback(update, context):
    query = update.callback_query
    query.answer()
    data = query.data
    if not data.startswith('checkpay:'):
        return
    payment_ref = data.split(':', 1)[1]
    p = db.get_payment_by_ref(payment_ref)
    if not p:
        query.edit_message_text('Платёж не найден. Свяжитесь с админом.')
        return
    ok, msg = payments.process_yoomoney_notification({'label': payment_ref, 'status': 'success', 'amount': p['amount']})
    if ok:
        query.edit_message_text('Оплата подтверждена автоматически. Подписка оформлена.')
    else:
        query.edit_message_text('Платёж не подтверждён автоматически. Ожидайте подтверждения админом.')


def my_cmd(update, context):
    uid = update.message.from_user.id
    rows = db.get_user_subscriptions(uid)
    if not rows:
        update.message.reply_text("У вас нет подписок.")
        return
    texts = []
    for r in rows:
        texts.append(f"{r['name']} — {r['code']} — до {r['expires_at']} UTC\n{r['link']}")
    update.message.reply_text("\n\n".join(texts))


def addplan_cmd(update, context):
    admin_id = cfg.get('main', 'admin_id', fallback='')
    if not admin_id or str(update.message.from_user.id) != str(admin_id):
        update.message.reply_text("Только админ может добавлять тарифы.")
        return
    args = context.args
    if len(args) < 3:
        update.message.reply_text("Использование: /addplan <name> <days> <price>")
        return
    name = args[0]
    try:
        days = int(args[1])
    except ValueError:
        update.message.reply_text("days должен быть целым числом")
        return
    price = args[2]
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO plans (name, days, price) VALUES (%s,%s,%s)", (name, days, price))
            conn.commit()
    update.message.reply_text("Тариф добавлен.")
