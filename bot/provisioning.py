"""Provisioning: create / renew / migrate VPN clients via the panel and keep
the local DB in sync. This is the bridge between payments and the panel.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import uuid as uuidlib
from typing import Any, Dict, Optional, Tuple

from . import db
from .config import CONFIG, Plan
from .core import xui
from .links import build_vless_link, fetch_direct_link, subscription_url

log = logging.getLogger("provisioning")

GB = 1024 * 1024 * 1024


def _gen_email(tg_id: int) -> str:
    return f"tg{tg_id}-{secrets.token_hex(3)}"


def _gen_sub_id() -> str:
    return secrets.token_hex(8)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _vless_flow(inbound_id: int) -> str:
    """Return client flow only when the inbound actually needs it."""
    if not CONFIG.flow:
        return ""
    try:
        inbound = xui.get_inbound(inbound_id)
        if inbound.get("protocol") != "vless":
            return ""
        stream = json.loads(inbound.get("streamSettings", "{}"))
        security = stream.get("security", "")
        network = stream.get("network", "tcp")
        # VLESS Reality (TCP) must use empty flow — xtls flow breaks the link.
        if security == "reality":
            return ""
        if network in ("tcp", "raw") and security in ("tls", "xtls"):
            return CONFIG.flow
        return CONFIG.flow
    except Exception:
        return ""


def _client_payload(
    protocol: str,
    *,
    inbound_id: int,
    uuid_str: str,
    email: str,
    sub_id: str,
    tg_id: int,
    total_bytes: int,
    expiry_ms: int,
    enable: bool = True,
) -> Dict[str, Any]:
    """Build a client dict matching the panel schema for the given protocol."""
    base = {
        "email": email,
        "limitIp": CONFIG.limit_ip,
        "totalGB": total_bytes,
        "expiryTime": expiry_ms,
        "enable": enable,
        "tgId": str(tg_id),
        "subId": sub_id,
        "comment": "kyzmichVPN bot",
        "reset": 0,
    }
    if protocol == "vmess":
        base["id"] = uuid_str
    elif protocol == "vless":
        base["id"] = uuid_str
        # Must always send flow (even ""), otherwise 3x-ui keeps the old value on update.
        base["flow"] = _vless_flow(inbound_id)
    elif protocol == "trojan":
        base["password"] = uuid_str
    elif protocol == "shadowsocks":
        base["password"] = uuid_str
        base["method"] = "chacha20-ietf-poly1305"
    else:
        base["id"] = uuid_str
    return base


def create_or_renew(tg_id: int, plan: Plan) -> Dict[str, Any]:
    """Create a new client or extend an existing subscription for the user.

    Returns the updated subscription record from the DB.
    """
    inbound_id = CONFIG.inbound_id
    protocol = xui.inbound_protocol(inbound_id)

    total_bytes = plan.total_bytes if plan.gb > 0 else (CONFIG.default_gb * GB)
    add_ms = plan.days * 24 * 60 * 60 * 1000

    existing = db.get_subscription(tg_id)

    if existing:
        # Extend from the later of "now" and the current expiry.
        base_expiry = existing["expiry_time"]
        start = max(_now_ms(), base_expiry) if base_expiry > 0 else _now_ms()
        new_expiry = start + add_ms

        client = _client_payload(
            protocol,
            inbound_id=existing["inbound_id"],
            uuid_str=existing["client_uuid"],
            email=existing["email"],
            sub_id=existing["sub_id"],
            tg_id=tg_id,
            total_bytes=total_bytes,
            expiry_ms=new_expiry,
            enable=True,
        )
        try:
            xui.update_client(existing["inbound_id"], existing["client_uuid"], client)
        except Exception:
            # Client may have been removed from the panel: recreate it.
            log.warning("Update failed for %s, recreating client.", existing["email"])
            xui.add_client(inbound_id, client)
        db.update_subscription_fields(
            tg_id,
            inbound_id=existing["inbound_id"],
            plan=plan.key,
            expiry_time=new_expiry,
            total_gb=plan.gb,
            enable=1,
        )
    else:
        client_uuid = str(uuidlib.uuid4())
        email = _gen_email(tg_id)
        sub_id = _gen_sub_id()
        new_expiry = _now_ms() + add_ms
        client = _client_payload(
            protocol,
            inbound_id=inbound_id,
            uuid_str=client_uuid,
            email=email,
            sub_id=sub_id,
            tg_id=tg_id,
            total_bytes=total_bytes,
            expiry_ms=new_expiry,
            enable=True,
        )
        xui.add_client(inbound_id, client)
        db.upsert_subscription(
            tg_id=tg_id,
            email=email,
            sub_id=sub_id,
            client_uuid=client_uuid,
            inbound_id=inbound_id,
            plan=plan.key,
            expiry_time=new_expiry,
            total_gb=plan.gb,
            enable=True,
        )

    return db.get_subscription(tg_id)


def repair_client_on_panel(sub: Dict[str, Any]) -> None:
    """Sync client settings on the panel (fixes invalid flow on Reality inbounds)."""
    try:
        inbound_id = sub["inbound_id"]
        protocol = xui.inbound_protocol(inbound_id)
        if protocol != "vless":
            return
        existing = xui.get_client_from_inbound(inbound_id, sub["email"])
        if not existing:
            return
        correct_flow = _vless_flow(inbound_id)
        if existing.get("flow", "") == correct_flow:
            return
        log.info(
            "Repairing client %s: flow %r -> %r",
            sub["email"],
            existing.get("flow"),
            correct_flow,
        )
        client = _client_payload(
            protocol,
            inbound_id=inbound_id,
            uuid_str=sub["client_uuid"],
            email=sub["email"],
            sub_id=sub["sub_id"],
            tg_id=sub["tg_id"],
            total_bytes=sub["total_gb"] * GB if sub["total_gb"] else 0,
            expiry_ms=sub["expiry_time"],
            enable=bool(sub["enable"]),
        )
        xui.update_client(inbound_id, sub["client_uuid"], client)
    except Exception as exc:
        log.warning("repair_client_on_panel failed for %s: %s", sub.get("email"), exc)


def set_enabled(sub: Dict[str, Any], enable: bool) -> None:
    protocol = xui.inbound_protocol(sub["inbound_id"])
    client = _client_payload(
        protocol,
        inbound_id=sub["inbound_id"],
        uuid_str=sub["client_uuid"],
        email=sub["email"],
        sub_id=sub["sub_id"],
        tg_id=sub["tg_id"],
        total_bytes=sub["total_gb"] * GB if sub["total_gb"] else 0,
        expiry_ms=sub["expiry_time"],
        enable=enable,
    )
    xui.update_client(sub["inbound_id"], sub["client_uuid"], client)
    db.update_subscription_fields(sub["tg_id"], enable=1 if enable else 0)


def extend_days(sub: Dict[str, Any], days: int) -> int:
    base_expiry = sub["expiry_time"]
    start = max(_now_ms(), base_expiry) if base_expiry > 0 else _now_ms()
    new_expiry = start + days * 24 * 60 * 60 * 1000
    protocol = xui.inbound_protocol(sub["inbound_id"])
    client = _client_payload(
        protocol,
        inbound_id=sub["inbound_id"],
        uuid_str=sub["client_uuid"],
        email=sub["email"],
        sub_id=sub["sub_id"],
        tg_id=sub["tg_id"],
        total_bytes=sub["total_gb"] * GB if sub["total_gb"] else 0,
        expiry_ms=new_expiry,
        enable=True,
    )
    xui.update_client(sub["inbound_id"], sub["client_uuid"], client)
    db.update_subscription_fields(sub["tg_id"], expiry_time=new_expiry, enable=1)
    return new_expiry


def delete_client(sub: Dict[str, Any]) -> None:
    try:
        xui.delete_client(sub["inbound_id"], sub["client_uuid"])
    except Exception as exc:
        log.warning("Failed to delete client %s on panel: %s", sub["email"], exc)
    db.delete_subscription(sub["tg_id"])


def reset_traffic(sub: Dict[str, Any]) -> None:
    xui.reset_client_traffic(sub["inbound_id"], sub["email"])


def migrate_to_inbound(sub: Dict[str, Any], target_inbound_id: int) -> Dict[str, Any]:
    """Recreate the user's client on a different inbound (new connection /
    new server config), removing it from the old inbound. Keeps the same
    email/subId so the subscription URL content is refreshed automatically.

    Returns the refreshed subscription record.
    """
    target_protocol = xui.inbound_protocol(target_inbound_id)
    client = _client_payload(
        target_protocol,
        inbound_id=target_inbound_id,
        uuid_str=sub["client_uuid"],
        email=sub["email"],
        sub_id=sub["sub_id"],
        tg_id=sub["tg_id"],
        total_bytes=sub["total_gb"] * GB if sub["total_gb"] else 0,
        expiry_ms=sub["expiry_time"],
        enable=bool(sub["enable"]),
    )

    # Add to the new inbound first, then remove from the old one.
    try:
        xui.add_client(target_inbound_id, client)
    except Exception as exc:
        # If it already exists on target, update instead.
        log.warning("Add on target inbound failed (%s); trying update.", exc)
        xui.update_client(target_inbound_id, sub["client_uuid"], client)

    if sub["inbound_id"] != target_inbound_id:
        try:
            xui.delete_client(sub["inbound_id"], sub["client_uuid"])
        except Exception as exc:
            log.warning("Failed to remove old client %s: %s", sub["email"], exc)

    db.update_subscription_fields(sub["tg_id"], inbound_id=target_inbound_id)
    return db.get_subscription(sub["tg_id"])


def connection_links(sub: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Return (subscription_url, direct_vless_link_or_None)."""
    repair_client_on_panel(sub)
    sub_url = subscription_url(sub["sub_id"])
    direct = fetch_direct_link(sub["sub_id"])
    if direct:
        return sub_url, direct
    try:
        inbound = xui.get_inbound(sub["inbound_id"])
        client = xui.get_client_from_inbound(sub["inbound_id"], sub["email"]) or {}
        direct = build_vless_link(inbound, client)
    except Exception as exc:
        log.warning("Could not build direct link for %s: %s", sub["email"], exc)
    return sub_url, direct
