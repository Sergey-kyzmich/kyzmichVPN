import threading
import time
import sys

# check telegram lib availability
try:
    from telegram.ext import Updater
except Exception as e:
    print("Missing or incompatible telegram library. Install 'python-telegram-bot' package:")
    print("python -m pip install python-telegram-bot==13.15")
    sys.exit(1)

from bot import create_updater
from web import app as flask_app
from app.config import cfg


def run_flask():
    port = int(cfg.get('webhook', 'port', fallback='8443'))
    host = cfg.get('webhook', 'listen', fallback='0.0.0.0')
    # Run Flask app
    flask_app.run(host=host, port=port)


def run_bot():
    updater = create_updater()
    # Always use polling in combined mode to avoid conflicts with Flask
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    t1 = threading.Thread(target=run_flask, daemon=True)
    t1.start()
    # slight delay for flask to start
    time.sleep(0.5)
    run_bot()
