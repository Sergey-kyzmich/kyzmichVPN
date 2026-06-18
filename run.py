"""kyzmichVPN Telegram bot — entry point.

Starts the Telegram long-polling loop and a background worker that confirms
pending YooKassa payments and provisions VPN access automatically.
"""

from __future__ import annotations

import logging
import threading
import time

from bot import db, payments
from bot.config import CONFIG, config_source_hint, reload_config
from bot.core import bot, xui

# Importing the handler modules registers their decorators on the bot.
from bot import handlers_user, handlers_admin  # noqa: E402,F401

log = logging.getLogger("run")

# How often the background worker checks pending payments (seconds).
PAYMENT_POLL_INTERVAL = 30
# Pending payments older than this are auto-cancelled (seconds).
PAYMENT_TTL = 60 * 60


def payment_worker() -> None:
    log.info("Payment worker started (interval=%ss).", PAYMENT_POLL_INTERVAL)
    while True:
        try:
            now_ms = int(time.time() * 1000)
            for payment in db.pending_payments():
                label = payment["label"]
                if now_ms - payment["created_at"] > PAYMENT_TTL * 1000:
                    db.mark_payment(label, "expired")
                    continue
                external_id = payment.get("external_id") or ""
                if external_id and payments.is_payment_succeeded(external_id):
                    log.info("Payment %s (YooKassa %s) confirmed by poller.", label, external_id)
                    handlers_user.finalize_payment(label)
        except Exception:
            log.exception("Payment worker iteration failed")
        time.sleep(PAYMENT_POLL_INTERVAL)


def main() -> None:
    db.init_db()
    cfg = reload_config()
    log.info("Config file: %s", config_source_hint())
    if not cfg.yookassa_shop_id or not cfg.yookassa_secret_key:
        log.warning("YooKassa keys are empty in the active config file: %s", config_source_hint())

    # Verify panel connectivity early (non-fatal if it fails; will retry lazily).
    try:
        xui.login()
        log.info("Panel reachable. Default inbound id=%s", CONFIG.inbound_id)
    except Exception as exc:
        log.warning("Could not log in to panel at startup: %s", exc)

    threading.Thread(target=payment_worker, daemon=True).start()

    log.info("Bot is starting (admins=%s)...", CONFIG.admins)
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)


if __name__ == "__main__":
    main()
