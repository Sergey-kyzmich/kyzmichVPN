import uuid
from urllib.parse import urlencode
import requests
from .config import cfg
from . import db
from .xray import create_xray_account
from telegram import Bot


YOOMONEY_ACCOUNT = cfg.get('yoomoney', 'account', fallback='')
YOOMONEY_TOKEN = cfg.get('yoomoney', 'token', fallback='')
BOT_TOKEN = cfg.get('bot', 'token', fallback='')


def create_payment(user_id, username, plan):
    payment_ref = f"p_{uuid.uuid4().hex}"
    amount = str(plan['price'])
    if not YOOMONEY_ACCOUNT:
        raise RuntimeError('YOOMONEY_ACCOUNT not configured')
    params = {
        'receiver': YOOMONEY_ACCOUNT,
        'formcomment': f'Оплата {plan["name"]}',
        'short-dest': plan['name'],
        'sum': amount,
        'label': payment_ref,
        'quickpay-form': 'shop',
        'paymentType': 'AC'
    }
    pay_link = f"https://yoomoney.ru/quickpay/confirm.xml?{urlencode(params)}"
    db.insert_payment(user_id, username, plan['id'], payment_ref, amount)
    return payment_ref, pay_link


def verify_yoomoney_payment(label, amount):
    if not YOOMONEY_TOKEN:
        return False
    headers = {'Authorization': f'OAuth {YOOMONEY_TOKEN}'}
    url = 'https://yoomoney.ru/api/operations'
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for op in data.get('operations', []):
            if op.get('label') == label and str(op.get('amount')) == str(amount):
                return True
    except Exception:
        return False
    return False


def process_yoomoney_notification(data):
    # Expecting at least 'label' (our payment_ref) and 'status' or 'amount'
    label = data.get('label') or data.get('notification_type')
    amount = data.get('amount')
    if not label:
        return False, 'no label'
    payment = db.get_payment_by_ref(label)
    if not payment:
        return False, 'payment not found'
    # Basic check: if notification indicates success, mark paid
    # YooMoney sends different payloads depending on config. Here we accept any notification with 'status'='success' or 'operation' type.
    status = data.get('status') or data.get('operation') or ''
    ok = False
    if status and 'success' in str(status).lower():
        ok = True
    # Fallback: if we have token, try API verify
    if not ok and YOOMONEY_TOKEN and amount:
        ok = verify_yoomoney_payment(label, amount)
    if ok:
        db.mark_payment_paid(label)
        # create subscription
        plan = db.get_plan_by_id(payment['plan_id'])
        # plan is dict
        account_uuid = f"{uuid.uuid4().hex}"
        try:
            if cfg.get('xray','api_url','') and cfg.get('xray','api_key',''):
                create_xray_account(account_uuid, plan['days'])
        except Exception:
            pass
        link = f"vless://{account_uuid}@{cfg.get('xray','host','')}:{cfg.get('xray','port','443')}?encryption=none&security=tls&type=tcp#{plan['name']}"
        db.insert_subscription(payment['user_id'], payment['username'], plan['id'], account_uuid, link, None)
        # notify user via telegram
        if BOT_TOKEN:
            bot = Bot(BOT_TOKEN)
            try:
                bot.send_message(payment['user_id'], f"Платёж получен. Ваша подписка: {link}")
            except Exception:
                pass
        return True, 'ok'
    return False, 'not confirmed'
