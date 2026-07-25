"""Async client for the Glowmarkt platform API.

Deliberately thin: it knows about authentication, the four endpoints this
integration needs, and nothing about Home Assistant.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Final

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import APPLICATION_ID, BASE_URL, FUNCTION_SUM

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT: Final = ClientTimeout(total=45)

# Tokens are documented as lasting 7 days. Renew an hour early so a long-running
# request can never straddle the expiry.
TOKEN_LEEWAY_SECONDS = 3600

API_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


class GlowmarktError(Exception):
    """Base error for the Glowmarkt API."""


class GlowmarktAuthError(GlowmarktError):
    """Credentials were rejected."""


class GlowmarktConnectionError(GlowmarktError):
    """The API could not be reached, or returned something unusable."""


class GlowmarktClient:
    """Talks to https://api.glowmarkt.com."""

    def __init__(
        self, session: ClientSession, username: str, password: str
    ) -> None:
        """Initialise the client."""
        self._session = session
        self._username = username
        self._password = password
        self._token: str | None = None
        self._token_expires: float = 0.0
        self._auth_lock = asyncio.Lock()

    async def async_login(self) -> None:
        """Exchange username/password for a JWT."""
        async with self._auth_lock:
            await self._async_login_locked()

    async def _async_login_locked(self) -> None:
        headers = {
            "Content-Type": "application/json",
            "applicationId": APPLICATION_ID,
        }
        payload = {"username": self._username, "password": self._password}

        try:
            async with self._session.post(
                f"{BASE_URL}/auth",
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    raise GlowmarktAuthError("Glowmarkt rejected the credentials")
                if response.status >= 400:
                    raise GlowmarktConnectionError(
                        f"Authentication failed with HTTP {response.status}"
                    )
                data = await response.json()
        except GlowmarktError:
            raise
        except (ClientError, TimeoutError, ValueError) as err:
            raise GlowmarktConnectionError(
                f"Could not reach the Glowmarkt API: {err}"
            ) from err

        # The API returns HTTP 200 with valid=false for a bad password, so the
        # status code alone is not enough to tell success from failure.
        if not data.get("valid") or not data.get("token"):
            raise GlowmarktAuthError("Glowmarkt rejected the credentials")

        self._token = data["token"]
        self._token_expires = float(data.get("exp") or 0)

    async def _async_valid_token(self) -> str:
        """Return a live token, logging in again if the current one is stale."""
        async with self._auth_lock:
            expired = (
                self._token is None
                or self._token_expires <= time.time() + TOKEN_LEEWAY_SECONDS
            )
            if expired:
                await self._async_login_locked()
            assert self._token is not None
            return self._token

    async def _async_get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        """GET a path, retrying once if the token turns out to be dead."""
        for attempt in (1, 2):
            token = await self._async_valid_token()
            headers = {
                "Content-Type": "application/json",
                "applicationId": APPLICATION_ID,
                "token": token,
            }
            try:
                async with self._session.get(
                    f"{BASE_URL}{path}",
                    params=params,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                ) as response:
                    if response.status in (401, 403):
                        # Force a fresh login and try once more before giving up.
                        self._token = None
                        self._token_expires = 0.0
                        if attempt == 1:
                            continue
                        raise GlowmarktAuthError(
                            "Glowmarkt rejected the session token"
                        )
                    if response.status >= 400:
                        raise GlowmarktConnectionError(
                            f"GET {path} failed with HTTP {response.status}"
                        )
                    return await response.json()
            except GlowmarktError:
                raise
            except (ClientError, TimeoutError, ValueError) as err:
                raise GlowmarktConnectionError(
                    f"Could not reach the Glowmarkt API: {err}"
                ) from err

        raise GlowmarktConnectionError(f"GET {path} failed")

    async def async_get_virtual_entities(self) -> list[dict[str, Any]]:
        """List the virtual entities (installations) on the account."""
        result = await self._async_get("/virtualentity")
        if not isinstance(result, list):
            raise GlowmarktConnectionError(
                "Unexpected response listing virtual entities"
            )
        return result

    async def async_get_resources(self, ve_id: str) -> list[dict[str, Any]]:
        """Return the fully described resources belonging to a virtual entity."""
        result = await self._async_get(f"/virtualentity/{ve_id}/resources")
        if not isinstance(result, dict):
            raise GlowmarktConnectionError(
                f"Unexpected response fetching resources for {ve_id}"
            )
        return result.get("resources") or []

    async def async_get_readings(
        self,
        resource_id: str,
        start: datetime,
        end: datetime,
        period: str,
        *,
        offset_minutes: int = 0,
        function: str = FUNCTION_SUM,
    ) -> list[tuple[int, float]]:
        """Return [(utc_timestamp, value)] for a resource over a time range.

        `start` and `end` must be naive local-wall-clock datetimes in whatever
        timezone `offset_minutes` describes. Per the API docs the offset is the
        minutes between the requested timezone and UTC, negated — so BST
        (UTC+1) is -60.
        """
        params = {
            "from": start.strftime(API_TIME_FORMAT),
            "to": end.strftime(API_TIME_FORMAT),
            "period": period,
            "offset": str(offset_minutes),
            "function": function,
        }
        result = await self._async_get(f"/resource/{resource_id}/readings", params)

        if not isinstance(result, dict):
            raise GlowmarktConnectionError(
                f"Unexpected readings response for resource {resource_id}"
            )

        readings: list[tuple[int, float]] = []
        for row in result.get("data") or []:
            # Rows are [timestamp, value]; value is null for periods with no data.
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            timestamp, value = row[0], row[1]
            if value is None or timestamp is None:
                continue
            try:
                readings.append((int(timestamp), float(value)))
            except (TypeError, ValueError):
                continue
        return readings
