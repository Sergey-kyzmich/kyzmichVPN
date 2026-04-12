from flask import Flask, request, jsonify
from app.payments import process_yoomoney_notification
from app.config import cfg

app = Flask(__name__)


@app.route('/yoomoney/webhook', methods=['POST'])
def yoomoney_webhook():
    secret = cfg.get('webhook', 'secret', fallback='')
    # optional simple secret check via header
    if secret:
        token = request.headers.get('X-Webhook-Token') or request.args.get('token')
        if token != secret:
            return jsonify({'ok': False, 'reason': 'invalid token'}), 403
    data = None
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()
    ok, msg = process_yoomoney_notification(data)
    if ok:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'reason': msg}), 400


if __name__ == '__main__':
    port = int(cfg.get('webhook', 'port', fallback='8443'))
    host = cfg.get('webhook', 'listen', fallback='0.0.0.0')
    app.run(host=host, port=port)
