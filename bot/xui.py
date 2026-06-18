"""3x-ui / x-ui panel HTTP API client.

Talks to the panel over its REST API. A single session cookie is kept and
re-acquired automatically when it expires. All client objects follow the
panel's schema (id/uuid, email, subId, expiryTime in ms, totalGB in bytes).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("xui")


class XUIError(Exception):
    pass


class XUIClient:
    def __init__(self, base_url: str, username: str, password: str, verify_tls: bool = False):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.verify_tls = verify_tls
        self._session = requests.Session()
        self._session.verify = verify_tls
        self._lock = threading.RLock()
        self._logged_in = False
        if not verify_tls:
            try:
                requests.packages.urllib3.disable_warnings()  # type: ignore
            except Exception:
                pass

    # ------------------------------------------------------------- internals
    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def login(self) -> None:
        with self._lock:
            resp = self._session.post(
                self._url("login"),
                data={"username": self.username, "password": self.password},
                timeout=20,
            )
            ok = False
            try:
                ok = resp.json().get("success", False)
            except Exception:
                ok = False
            if not ok:
                raise XUIError(f"Login to panel failed (status {resp.status_code}).")
            self._logged_in = True
            log.info("Logged in to 3x-ui panel.")

    def _request(self, method: str, path: str, *, retry: bool = True, **kwargs) -> Dict[str, Any]:
        with self._lock:
            if not self._logged_in:
                self.login()
            resp = self._session.request(method, self._url(path), timeout=30, **kwargs)
            # Session expired -> panel redirects to login (returns HTML).
            content_type = resp.headers.get("Content-Type", "")
            if resp.status_code in (401, 403) or "application/json" not in content_type:
                if retry:
                    self._logged_in = False
                    self.login()
                    return self._request(method, path, retry=False, **kwargs)
                raise XUIError(f"Unexpected response from {path}: {resp.status_code} {resp.text[:200]}")
            try:
                data = resp.json()
            except Exception as exc:
                raise XUIError(f"Invalid JSON from {path}: {exc}")
            return data

    # --------------------------------------------------------------- inbounds
    def list_inbounds(self) -> List[Dict[str, Any]]:
        data = self._request("GET", "panel/api/inbounds/list")
        if not data.get("success"):
            raise XUIError(data.get("msg", "Failed to list inbounds"))
        return data.get("obj", []) or []

    def get_inbound(self, inbound_id: int) -> Dict[str, Any]:
        data = self._request("GET", f"panel/api/inbounds/get/{inbound_id}")
        if not data.get("success"):
            raise XUIError(data.get("msg", "Failed to get inbound"))
        return data.get("obj", {})

    def inbound_protocol(self, inbound_id: int) -> str:
        return self.get_inbound(inbound_id).get("protocol", "vless")

    # ---------------------------------------------------------------- clients
    def add_client(self, inbound_id: int, client: Dict[str, Any]) -> None:
        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        data = self._request(
            "POST", "panel/api/inbounds/addClient", json=payload
        )
        if not data.get("success"):
            raise XUIError(data.get("msg", "Failed to add client"))

    def update_client(self, inbound_id: int, client_uuid: str, client: Dict[str, Any]) -> None:
        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        data = self._request(
            "POST", f"panel/api/inbounds/updateClient/{client_uuid}", json=payload
        )
        if not data.get("success"):
            raise XUIError(data.get("msg", "Failed to update client"))

    def delete_client(self, inbound_id: int, client_uuid: str) -> None:
        data = self._request(
            "POST", f"panel/api/inbounds/{inbound_id}/delClient/{client_uuid}"
        )
        if not data.get("success"):
            raise XUIError(data.get("msg", "Failed to delete client"))

    def get_client_traffic(self, email: str) -> Optional[Dict[str, Any]]:
        data = self._request("GET", f"panel/api/inbounds/getClientTraffics/{email}")
        if not data.get("success"):
            return None
        return data.get("obj")

    def reset_client_traffic(self, inbound_id: int, email: str) -> None:
        data = self._request(
            "POST", f"panel/api/inbounds/{inbound_id}/resetClientTraffic/{email}"
        )
        if not data.get("success"):
            raise XUIError(data.get("msg", "Failed to reset traffic"))

    def online_clients(self) -> List[str]:
        try:
            data = self._request("POST", "panel/api/inbounds/onlines")
            return data.get("obj", []) or []
        except XUIError:
            return []

    # ------------------------------------------------------------- inbound IO
    def get_client_from_inbound(self, inbound_id: int, email: str) -> Optional[Dict[str, Any]]:
        """Find a client object in an inbound's settings by email."""
        inbound = self.get_inbound(inbound_id)
        try:
            settings = json.loads(inbound.get("settings", "{}"))
        except json.JSONDecodeError:
            return None
        for client in settings.get("clients", []):
            if client.get("email") == email:
                return client
        return None
