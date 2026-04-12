import psycopg2
from psycopg2.extras import RealDictCursor
from .config import cfg


def get_conn():
    url = cfg.get('db', 'url', fallback='')
    return psycopg2.connect(url)


def init_db():
    sql = open("schema.sql", "r", encoding="utf-8").read()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()


def list_plans():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id,name,days,price FROM plans ORDER BY id")
            return cur.fetchall()


def get_plan_by_id(plan_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id,name,days,price FROM plans WHERE id=%s", (plan_id,))
            return cur.fetchone()


def insert_payment(user_id, username, plan_id, payment_ref, amount):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO payments (user_id, username, plan_id, payment_ref, amount) VALUES (%s,%s,%s,%s,%s)",
                        (user_id, username, plan_id, payment_ref, amount))
            conn.commit()


def get_payment_by_ref(payment_ref):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT * FROM payments WHERE payment_ref=%s', (payment_ref,))
            return cur.fetchone()


def mark_payment_paid(payment_ref):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE payments SET status='paid', paid_at=NOW() WHERE payment_ref=%s", (payment_ref,))
            conn.commit()


def insert_subscription(user_id, username, plan_id, code, link, expires_at):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO subscriptions (user_id, username, plan_id, code, link, expires_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (user_id, username, plan_id, code, link, expires_at),
            )
            conn.commit()


def get_user_subscriptions(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT s.code, s.link, s.expires_at, p.name FROM subscriptions s JOIN plans p ON s.plan_id=p.id WHERE s.user_id=%s ORDER BY s.expires_at DESC",
                (user_id,)
            )
            return cur.fetchall()
