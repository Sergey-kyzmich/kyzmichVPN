import os
import configparser


def load_config(path="config.ini"):
    cfg = configparser.ConfigParser()
    if os.path.exists(path):
        cfg.read(path)
    else:
        cfg['bot'] = {'token': os.getenv('BOT_TOKEN', '')}
        cfg['db'] = {'url': os.getenv('DATABASE_URL', '')}
        cfg['xray'] = {'host': os.getenv('XRAY_HOST', ''), 'port': os.getenv('XRAY_PORT', '443'), 'api_url': os.getenv('XRAY_API_URL', ''), 'api_key': os.getenv('XRAY_API_KEY', '')}
        cfg['yoomoney'] = {'account': os.getenv('YOOMONEY_ACCOUNT', ''), 'token': os.getenv('YOOMONEY_TOKEN', '')}
        cfg['main'] = {'admin_id': os.getenv('ADMIN_ID', '')}
        cfg['webhook'] = {'url': os.getenv('WEBHOOK_URL', ''), 'port': os.getenv('WEBHOOK_PORT', '8443'), 'path': os.getenv('WEBHOOK_PATH', '')}
    return cfg


cfg = load_config()


def get(key, section='DEFAULT', fallback=''):
    try:
        return cfg.get(section, key, fallback=fallback)
    except Exception:
        return fallback
