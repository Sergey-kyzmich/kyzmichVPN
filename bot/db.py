"""SQLite persistence layer.

Tracks Telegram users, their VPN subscription (one active client per user
in the panel) and the payment history. The panel (3x-ui) remains the source
of truth for live traffic; this DB stores the mapping and local bookkeeping.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get(
    "KYZMICH_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kyzmich.db"),
)

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
    return _conn


def init_db() -> None:
    with _lock:
        conn = _connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                tg_id        INTEGER PRIMARY KEY,
                username     TEXT,
                first_name   TEXT,
                is_blocked   INTEGER NOT NULL DEFAULT 0,
                created_at   INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                tg_id        INTEGER PRIMARY KEY,
                email        TEXT NOT NULL,
                sub_id       TEXT NOT NULL,
                client_uuid  TEXT NOT NULL,
                inbound_id   INTEGER NOT NULL,
                plan         TEXT,
                expiry_time  INTEGER NOT NULL DEFAULT 0,
                total_gb     INTEGER NOT NULL DEFAULT 0,
                enable       INTEGER NOT NULL DEFAULT 1,
                created_at   INTEGER NOT NULL,
                updated_at   INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id        INTEGER NOT NULL,
                label        TEXT NOT NULL UNIQUE,
                external_id  TEXT,
                plan         TEXT NOT NULL,
                amount       REAL NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                created_at   INTEGER NOT NULL,
                paid_at      INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_email ON subscriptions(email);
            """
        )
        _migrate_payments(conn)
        conn.commit()


def _migrate_payments(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(payments)")}
    if "external_id" not in cols:
        conn.execute("ALTER TABLE payments ADD COLUMN external_id TEXT")


def now_ms() -> int:
    return int(time.time() * 1000)


# --------------------------------------------------------------------- users
def upsert_user(tg_id: int, username: Optional[str], first_name: Optional[str]) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO users (tg_id, username, first_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username,
                                             first_name=excluded.first_name
            """,
            (tg_id, username, first_name, now_ms()),
        )
        conn.commit()


def get_user(tg_id: int) -> Optional[Dict[str, Any]]:
    with _lock:
        row = _connect().execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        return dict(row) if row else None


def set_blocked(tg_id: int, blocked: bool) -> None:
    with _lock:
        conn = _connect()
        conn.execute("UPDATE users SET is_blocked=? WHERE tg_id=?", (1 if blocked else 0, tg_id))
        conn.commit()


def all_users() -> List[Dict[str, Any]]:
    with _lock:
        rows = _connect().execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def count_users() -> int:
    with _lock:
        return _connect().execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


# ------------------------------------------------------------- subscriptions
def get_subscription(tg_id: int) -> Optional[Dict[str, Any]]:
    with _lock:
        row = _connect().execute("SELECT * FROM subscriptions WHERE tg_id=?", (tg_id,)).fetchone()
        return dict(row) if row else None


def upsert_subscription(
    tg_id: int,
    email: str,
    sub_id: str,
    client_uuid: str,
    inbound_id: int,
    plan: str,
    expiry_time: int,
    total_gb: int,
    enable: bool = True,
) -> None:
    ts = now_ms()
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO subscriptions
                (tg_id, email, sub_id, client_uuid, inbound_id, plan,
                 expiry_time, total_gb, enable, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
                email=excluded.email,
                sub_id=excluded.sub_id,
                client_uuid=excluded.client_uuid,
                inbound_id=excluded.inbound_id,
                plan=excluded.plan,
                expiry_time=excluded.expiry_time,
                total_gb=excluded.total_gb,
                enable=excluded.enable,
                updated_at=excluded.updated_at
            """,
            (tg_id, email, sub_id, client_uuid, inbound_id, plan, expiry_time,
             total_gb, 1 if enable else 0, ts, ts),
        )
        conn.commit()


def update_subscription_fields(tg_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = now_ms()
    cols = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [tg_id]
    with _lock:
        conn = _connect()
        conn.execute(f"UPDATE subscriptions SET {cols} WHERE tg_id=?", values)
        conn.commit()


def delete_subscription(tg_id: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM subscriptions WHERE tg_id=?", (tg_id,))
        conn.commit()


def all_subscriptions() -> List[Dict[str, Any]]:
    with _lock:
        rows = _connect().execute(
            "SELECT * FROM subscriptions ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def active_subscriptions() -> List[Dict[str, Any]]:
    """Subscriptions that are enabled and not expired."""
    ts = now_ms()
    with _lock:
        rows = _connect().execute(
            "SELECT * FROM subscriptions WHERE enable=1 AND (expiry_time=0 OR expiry_time>?)",
            (ts,),
        ).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------ payments
def create_payment(
    tg_id: int,
    label: str,
    plan: str,
    amount: float,
    external_id: str = "",
) -> int:
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO payments (tg_id, label, external_id, plan, amount, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (tg_id, label, external_id or None, plan, amount, now_ms()),
        )
        conn.commit()
        return cur.lastrowid


def get_payment_by_label(label: str) -> Optional[Dict[str, Any]]:
    with _lock:
        row = _connect().execute("SELECT * FROM payments WHERE label=?", (label,)).fetchone()
        return dict(row) if row else None


def mark_payment(label: str, status: str) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "UPDATE payments SET status=?, paid_at=? WHERE label=?",
            (status, now_ms() if status == "success" else None, label),
        )
        conn.commit()


def pending_payments() -> List[Dict[str, Any]]:
    with _lock:
        rows = _connect().execute(
            "SELECT * FROM payments WHERE status='pending' ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def payments_of_user(tg_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    with _lock:
        rows = _connect().execute(
            "SELECT * FROM payments WHERE tg_id=? ORDER BY created_at DESC LIMIT ?",
            (tg_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def revenue() -> float:
    with _lock:
        row = _connect().execute(
            "SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE status='success'"
        ).fetchone()
        return float(row["s"])
