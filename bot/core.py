"""Shared singletons: the Telegram bot instance and the panel API client."""

from __future__ import annotations

import logging

import telebot

from .config import CONFIG
from .xui import XUIClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if CONFIG.proxy:
    telebot.apihelper.proxy = {"https": CONFIG.proxy}

bot = telebot.TeleBot(CONFIG.token, parse_mode="HTML", threaded=True)

xui = XUIClient(
    base_url=CONFIG.xui_base_url,
    username=CONFIG.xui_username,
    password=CONFIG.xui_password,
)
