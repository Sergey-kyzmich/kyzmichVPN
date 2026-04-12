import requests
from .config import cfg


XRAY_API_URL = cfg.get('xray', 'api_url', fallback='')
XRAY_API_KEY = cfg.get('xray', 'api_key', fallback='')


def create_xray_account(account_uuid, days):
    if not XRAY_API_URL or not XRAY_API_KEY:
        raise RuntimeError('XRAY API not configured')
    payload = {'uuid': account_uuid, 'expiry_days': int(days)}
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {XRAY_API_KEY}'}
    resp = requests.post(XRAY_API_URL, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()
