from telegram.ext import Updater, CommandHandler, CallbackQueryHandler
from telegram.ext import Dispatcher
from app.config import cfg
from app import db
from app.handlers import start, plans_cmd, buy_callback, checkpay_callback, my_cmd, addplan_cmd


def main():
    token = cfg.get('bot', 'token', fallback='')
    if not token:
        print('Set BOT token in config.ini')
        return
    # init DB
    db.init_db()
    updater = create_updater()
    webhook_url = cfg.get('webhook', 'url', fallback='')
    if webhook_url:
        listen = cfg.get('webhook', 'listen', fallback='0.0.0.0')
        port = int(cfg.get('webhook', 'port', fallback='8443'))
        path = cfg.get('webhook', 'path', fallback=token)
        updater.start_webhook(listen=listen, port=port, url_path=path)
        updater.bot.set_webhook(webhook_url.rstrip('/') + '/' + path)
        updater.idle()
    else:
        updater.start_polling()
        updater.idle()


def create_updater():
    """Create and return a configured Updater instance (not started)."""
    token = cfg.get('bot', 'token', fallback='')
    updater = Updater(token, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('plans', plans_cmd))
    dp.add_handler(CallbackQueryHandler(checkpay_callback, pattern='^checkpay:'))
    dp.add_handler(CallbackQueryHandler(buy_callback, pattern='^buy:'))
    dp.add_handler(CommandHandler('my', my_cmd))
    dp.add_handler(CommandHandler('addplan', addplan_cmd))
    return updater


if __name__ == '__main__':
    main()
