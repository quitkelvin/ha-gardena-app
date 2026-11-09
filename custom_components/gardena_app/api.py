"""Client for the private API the GARDENA smart app uses (smart.gardena.com/v1).

Authentication uses the Husqvarna developer application (client credentials),
the same key and secret the official GARDENA smart system integration needs.
Unlike the official API this one exposes the app's schedules and settings.
"""

from __future__ import annotations

import re
import time
from typing import Any

import aiohttp

from .const import APP_URL, AUTH_URL


class GardenaError(Exception):
    """Communication with the GARDENA cloud failed."""


class GardenaAuthError(GardenaError):
    """Client key or secret were rejected."""


_CODE_OK = re.compile(r"[^a-z0-9_.-]")


async def _error_code(resp: aiohttp.ClientResponse) -> str:
    """Short, sanitised error code from a failed response; never the raw body.

    Error bodies can echo account, location or device data, so only a code like
    ``invalid_client`` (lower case, at most 40 characters of [a-z0-9_.-]) is kept.
    """
    try:
        body = await resp.json(content_type=None)
    except (aiohttp.ClientError, ValueError):
        return "unknown"
    code: Any = None
    if isinstance(body, dict):
        code = body.get("error") or body.get("code")
        errors = body.get("errors")
        if not code and isinstance(errors, list) and errors and isinstance(errors[0], dict):
            code = errors[0].get("code")
    if not isinstance(code, (str, int)):
        return "unknown"
    return _CODE_OK.sub("_", str(code).strip().lower())[:40] or "unknown"


def _route(path: str) -> str:
    """Endpoint name without ids or query string (``/devices/<id>/...`` -> ``/devices``)."""
    return "/" + path.lstrip("/").split("?", 1)[0].split("/", 1)[0]


class GardenaAppClient:
    """Thin async wrapper around the app endpoints."""

    def __init__(self, session: aiohttp.ClientSession, client_id: str, client_secret: str) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_until = 0.0
        self.user_id: str | None = None
        self.location_id: str | None = None

    async def _ensure_token(self) -> None:
        if self._token and time.monotonic() < self._token_until:
            return
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        try:
            async with self._session.post(AUTH_URL, data=data, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status >= 400:
                    code = await _error_code(resp)
                    # Only a rejected key/secret is fatal; anything else (rate limit, hiccup) is retried.
                    if resp.status in (401, 403) or code == "invalid_client":
                        raise GardenaAuthError(f"token request rejected (HTTP {resp.status}, {code})")
                    raise GardenaError(f"token request failed (HTTP {resp.status}, {code})")
                body = await resp.json()
        except aiohttp.ClientError as err:
            # The exception text can contain the request URL; keep only its type.
            raise GardenaError(f"token request failed ({type(err).__name__})") from None
        self._token = body["access_token"]
        self._token_until = time.monotonic() + int(body.get("expires_in", 3600)) - 120
        self.user_id = body.get("user_id")

    async def _request(self, method: str, path: str, payload: dict | None = None, retry: bool = True) -> Any:
        await self._ensure_token()
        params = {"locationId": self.location_id} if self.location_id else None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Authorization-Provider": "husqvarna",
            "X-Api-Key": self._client_id,
            "Content-Type": "application/json",
        }
        try:
            async with self._session.request(
                method, APP_URL + path, params=params, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401 and retry:
                    self._token = None
                    return await self._request(method, path, payload, retry=False)
                if resp.status >= 400:
                    raise GardenaError(f"{method} {_route(path)} failed (HTTP {resp.status}, {await _error_code(resp)})")
                if resp.status == 204:
                    return None
                text = await resp.text()
                return None if not text else await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            # The exception text can contain the URL with account/device ids; keep only its type.
            raise GardenaError(f"{method} {_route(path)} failed ({type(err).__name__})") from None

    async def async_locate(self) -> str:
        """Find the first location of the account."""
        await self._ensure_token()
        body = await self._request("GET", f"/locations?user_id={self.user_id}")
        locations = body.get("locations") or []
        if not locations:
            raise GardenaError("no GARDENA location on this account")
        self.location_id = locations[0]["id"]
        return locations[0].get("name") or "GARDENA"

    async def async_devices(self) -> list[dict]:
        body = await self._request("GET", "/devices")
        return body.get("devices", [])

    async def async_put_setting(self, device_id: str, setting: dict, value: Any) -> None:
        await self._request(
            "PUT", f"/devices/{device_id}/settings/{setting['id']}",
            {"settings": {"name": setting["name"], "value": value, "device": device_id}},
        )

    async def async_put_property(self, device_id: str, ability: str, name: str, value: Any) -> None:
        await self._request(
            "PUT", f"/devices/{device_id}/abilities/{ability}/properties/{name}",
            {"properties": {"name": name, "value": value}},
        )

    async def async_command(self, device_id: str, ability: str, name: str, parameters: dict | None = None) -> None:
        await self._request(
            "POST", f"/devices/{device_id}/abilities/{ability}/command",
            {"name": name, "parameters": parameters or {}},
        )

    async def async_add_event(self, device_id: str, event: dict) -> dict:
        body = await self._request(
            "POST", f"/devices/{device_id}/scheduled_events",
            {"scheduled_events": {**event, "device": device_id}},
        )
        return (body or {}).get("scheduled_event", {})

    async def async_update_event(self, device_id: str, event_id: str, event: dict) -> None:
        await self._request(
            "PUT", f"/devices/{device_id}/scheduled_events/{event_id}",
            {"scheduled_events": {**event, "id": event_id, "device": device_id}},
        )

    async def async_delete_event(self, device_id: str, event_id: str) -> None:
        await self._request("DELETE", f"/devices/{device_id}/scheduled_events/{event_id}")
