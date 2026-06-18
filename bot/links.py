"""Build connection artifacts for a client: subscription URL, direct link from
the panel's subscription endpoint (correct per-client Reality params), and QR.

The subscription URL is always correct. Direct links are fetched from the
panel subscription content (same as 3x-ui's «individual links»). Manual
``vless://`` assembly is only a last-resort fallback.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode, urlparse

import qrcode
import requests

from .config import CONFIG

log = logging.getLogger("links")


def subscription_url(sub_id: str) -> str:
    base = CONFIG.sub_base_url.rstrip("/")
    return f"{base}/{sub_id}" if base else ""


def _host_from_base() -> str:
    parsed = urlparse(CONFIG.sub_base_url or CONFIG.xui_base_url)
    return parsed.hostname or "localhost"


def _decode_subscription_body(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    # 3x-ui may return base64 when «Encrypt subscription» is enabled.
    if text.startswith("vless://") or text.startswith("vmess://") or text.startswith("trojan://"):
        return text
    try:
        decoded = base64.b64decode(text, validate=True).decode("utf-8", errors="replace")
        if decoded.strip():
            return decoded
    except Exception:
        pass
    return text


def fetch_subscription_links(sub_id: str) -> List[str]:
    """Fetch individual connection links from the panel subscription endpoint."""
    url = subscription_url(sub_id)
    if not url:
        return []
    try:
        resp = requests.get(
            url,
            headers={"Accept": "text/plain, */*;q=0.1"},
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
    except Exception as exc:
        log.warning("Failed to fetch subscription %s: %s", url, exc)
        return []

    content = _decode_subscription_body(resp.content)
    links: List[str] = []
    for line in content.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if line:
            links.append(line)
    return links


def fetch_direct_link(sub_id: str) -> Optional[str]:
    """Return the first vless:// link from the subscription, or any first link."""
    links = fetch_subscription_links(sub_id)
    for link in links:
        if link.startswith("vless://"):
            return link
    return links[0] if links else None


def build_vless_link(inbound: Dict[str, Any], client: Dict[str, Any]) -> Optional[str]:
    """Fallback vless:// builder when subscription fetch is unavailable."""
    if inbound.get("protocol") != "vless":
        return None

    uuid = client.get("id")
    if not uuid:
        return None

    port = inbound.get("port")
    host = _host_from_base()
    remark = inbound.get("remark", "vpn")
    label = str(remark).replace(" ", "-")

    try:
        stream = json.loads(inbound.get("streamSettings", "{}"))
    except json.JSONDecodeError:
        stream = {}

    network = stream.get("network", "tcp")
    security = stream.get("security", "none")

    params: Dict[str, str] = {
        "encryption": "none",
        "type": network,
        "security": security,
    }

    # Reality + TCP must NOT include flow (breaks connection).
    flow = client.get("flow") or ""
    if flow and not (security == "reality" and network in ("tcp", "raw")):
        params["flow"] = flow

    if security == "reality":
        reality = stream.get("realitySettings", {})
        rset = reality.get("settings", {})
        server_names = reality.get("serverNames", []) or []
        short_ids = reality.get("shortIds", []) or [""]
        if server_names:
            params["sni"] = server_names[0]
        if rset.get("publicKey"):
            params["pbk"] = rset["publicKey"]
        if short_ids and short_ids[0]:
            params["sid"] = short_ids[0]
        if rset.get("fingerprint"):
            params["fp"] = rset["fingerprint"]
        if rset.get("spiderX"):
            params["spx"] = rset["spiderX"]
        # Post-quantum Reality (newer 3x-ui / xray).
        pqv = rset.get("mldsa65Verify") or rset.get("pqv")
        if pqv:
            params["pqv"] = pqv
    elif security == "tls":
        tls = stream.get("tlsSettings", {})
        if tls.get("serverName"):
            params["sni"] = tls["serverName"]
        fp = tls.get("settings", {}).get("fingerprint")
        if fp:
            params["fp"] = fp
        alpn = tls.get("alpn")
        if alpn:
            params["alpn"] = ",".join(alpn)

    if network == "ws":
        ws = stream.get("wsSettings", {})
        if ws.get("path"):
            params["path"] = ws["path"]
        ws_host = ws.get("headers", {}).get("Host")
        if ws_host:
            params["host"] = ws_host
    elif network == "grpc":
        grpc = stream.get("grpcSettings", {})
        if grpc.get("serviceName"):
            params["serviceName"] = grpc["serviceName"]
    elif network in ("tcp", "raw"):
        tcp = stream.get("tcpSettings", stream.get("rawSettings", {}))
        header = tcp.get("header", {})
        if header.get("type") == "http":
            params["headerType"] = "http"
            params.setdefault("path", "/")
            req_hosts = header.get("request", {}).get("headers", {}).get("Host", [])
            if req_hosts:
                params["host"] = ",".join(req_hosts)

    query = urlencode({k: v for k, v in params.items() if v}, quote_via=quote)
    return f"vless://{uuid}@{host}:{port}?{query}#{quote(label)}"


def make_qr(data: str) -> io.BytesIO:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    buf.name = "vpn.png"
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
