"""ЮKassa (YooKassa) payment integration.

Creates redirect payments via the official API and checks their status by
polling (background worker + manual «Я оплатил» button). No public webhook
endpoint is required.

Requires in config.ini [yookassa]:
  * shop_id    — идентификатор магазина (account_id)
  * secret_key — секретный ключ API
  * return_url — URL возврата после оплаты (можно ссылку на бота)
"""

from __future__ import annotations

import logging
import os
import uuid as uuidlib
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple

from yookassa import Configuration, Payment

from .config import CONFIG, _DEFAULT_CONFIG_PATH, config_source_hint, load_config, reload_config

log = logging.getLogger("payments")


def _ensure_configured() -> None:
    cfg = reload_config()
    if not cfg.yookassa_shop_id or not cfg.yookassa_secret_key:
        hint = config_source_hint()
        extra = ""
        if os.environ.get("KYZMICH_CONFIG") and os.path.isfile(_DEFAULT_CONFIG_PATH):
            fallback = load_config(_DEFAULT_CONFIG_PATH)
            if fallback.yookassa_shop_id and fallback.yookassa_secret_key:
                extra = (
                    f"\n\nВ {_DEFAULT_CONFIG_PATH} ключи указаны, "
                    f"но бот читает другой файл из-за KYZMICH_CONFIG.\n"
                    f"Удалите переменную: Remove-Item Env:KYZMICH_CONFIG (PowerShell) "
                    f"или перезапустите терминал."
                )
        raise RuntimeError(
            f"yookassa.shop_id и yookassa.secret_key не найдены в конфиге.\n"
            f"Активный файл: {hint}{extra}"
        )
    Configuration.account_id = cfg.yookassa_shop_id
    Configuration.secret_key = cfg.yookassa_secret_key


def new_label(tg_id: int) -> str:
    """Internal payment label (stored in DB and YooKassa metadata)."""
    return f"kyzmich-{tg_id}-{uuidlib.uuid4().hex[:12]}"


def _format_amount(amount: float) -> str:
    """YooKassa expects a string with exactly two decimal places."""
    return str(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def create_yookassa_payment(
    *,
    label: str,
    tg_id: int,
    plan_key: str,
    amount: float,
    description: str,
) -> Tuple[str, str]:
    """Create a YooKassa payment. Returns (payment_id, confirmation_url)."""
    _ensure_configured()
    idempotence_key = str(uuidlib.uuid4())
    payload = {
        "amount": {"value": _format_amount(amount), "currency": CONFIG.currency},
        "confirmation": {
            "type": "redirect",
            "return_url": CONFIG.yookassa_return_url or "https://t.me/",
        },
        "capture": True,
        "description": description[:128],
        "metadata": {
            "label": label,
            "tg_id": str(tg_id),
            "plan": plan_key,
        },
    }
    try:
        payment = Payment.create(payload, idempotence_key)
    except Exception as exc:
        log.exception("YooKassa Payment.create failed")
        raise RuntimeError(f"Не удалось создать платёж в ЮKassa: {exc}") from exc

    payment_id = payment.id
    confirmation_url = payment.confirmation.confirmation_url
    if not payment_id or not confirmation_url:
        raise RuntimeError("ЮKassa вернула неполный ответ (нет id или ссылки на оплату)")
    return payment_id, confirmation_url


def is_payment_succeeded(external_id: str) -> bool:
    """Return True if the YooKassa payment status is succeeded."""
    if not external_id:
        return False
    _ensure_configured()
    try:
        payment = Payment.find_one(external_id)
    except Exception as exc:
        log.warning("YooKassa status check failed for %s: %s", external_id, exc)
        return False
    status = (payment.status or "").lower()
    return status == "succeeded"
