"""Tests for the Glowmarkt HTTP client."""

from __future__ import annotations

from datetime import datetime

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.glowmarkt.api import (
    GlowmarktAuthError,
    GlowmarktClient,
    GlowmarktConnectionError,
)
from custom_components.glowmarkt.const import BASE_URL

from .const import AUTH_OK, AUTH_REJECTED, PASSWORD, USERNAME


def _client(hass: HomeAssistant) -> GlowmarktClient:
    return GlowmarktClient(async_get_clientsession(hass), USERNAME, PASSWORD)


async def test_login_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A valid response yields a usable token."""
    aioclient_mock.post(f"{BASE_URL}/auth", json=AUTH_OK)

    client = _client(hass)
    await client.async_login()

    assert aioclient_mock.call_count == 1
    # applicationId identifies the Bright app and must always be sent.
    assert aioclient_mock.mock_calls[0][3]["applicationId"]


async def test_login_rejected_returns_http_200(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A bad password comes back as 200 with valid=false, not as a 401."""
    aioclient_mock.post(f"{BASE_URL}/auth", json=AUTH_REJECTED)

    with pytest.raises(GlowmarktAuthError):
        await _client(hass).async_login()


async def test_login_unauthorised_status(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An explicit 401 is also an auth error."""
    aioclient_mock.post(f"{BASE_URL}/auth", status=401)

    with pytest.raises(GlowmarktAuthError):
        await _client(hass).async_login()


async def test_login_server_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 500 is a connection problem, not a credential problem."""
    aioclient_mock.post(f"{BASE_URL}/auth", status=500)

    with pytest.raises(GlowmarktConnectionError):
        await _client(hass).async_login()


async def test_get_virtual_entities(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Virtual entities are returned and the token header is sent."""
    aioclient_mock.post(f"{BASE_URL}/auth", json=AUTH_OK)
    aioclient_mock.get(
        f"{BASE_URL}/virtualentity", json=[{"name": "Home", "veId": "ve-1"}]
    )

    result = await _client(hass).async_get_virtual_entities()

    assert [ve["veId"] for ve in result] == ["ve-1"]
    assert aioclient_mock.mock_calls[-1][3]["token"] == AUTH_OK["token"]


async def test_get_resources_unwraps_the_document(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The resources endpoint returns a VE document, not a bare list."""
    aioclient_mock.post(f"{BASE_URL}/auth", json=AUTH_OK)
    aioclient_mock.get(
        f"{BASE_URL}/virtualentity/ve-1/resources",
        json={"veId": "ve-1", "resources": [{"resourceId": "r1"}]},
    )

    result = await _client(hass).async_get_resources("ve-1")

    assert result == [{"resourceId": "r1"}]


async def test_readings_parsed_and_nulls_skipped(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Null readings are dropped rather than counted as zero."""
    aioclient_mock.post(f"{BASE_URL}/auth", json=AUTH_OK)
    aioclient_mock.get(
        f"{BASE_URL}/resource/r1/readings",
        json={
            "status": "OK",
            "data": [
                [1523318400, 48.79],
                [1523322000, None],
                [1523325600, 1.5],
                ["bad", "row"],
                [1523329200],
            ],
        },
    )

    result = await _client(hass).async_get_readings(
        "r1", datetime(2018, 4, 10), datetime(2018, 4, 11), "PT1H"
    )

    assert result == [(1523318400, 48.79), (1523325600, 1.5)]


async def test_expired_token_triggers_one_retry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 mid-session re-authenticates and retries the request once."""
    aioclient_mock.post(f"{BASE_URL}/auth", json=AUTH_OK)
    aioclient_mock.get(f"{BASE_URL}/virtualentity", status=401)

    with pytest.raises(GlowmarktAuthError):
        await _client(hass).async_get_virtual_entities()

    # Two auth attempts: the initial login, then the forced retry.
    auth_calls = [c for c in aioclient_mock.mock_calls if c[1].path.endswith("/auth")]
    assert len(auth_calls) == 2
