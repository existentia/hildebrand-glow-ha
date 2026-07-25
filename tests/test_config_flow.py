"""Tests for the Glowmarkt config and reauth flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.glowmarkt.api import (
    GlowmarktAuthError,
    GlowmarktConnectionError,
)
from custom_components.glowmarkt.const import DOMAIN

from .const import PASSWORD, USERNAME, VIRTUAL_ENTITIES

CLIENT_PATH = "custom_components.glowmarkt.config_flow.GlowmarktClient"


def _mock_client(virtual_entities=VIRTUAL_ENTITIES, login_error=None):
    client = AsyncMock()
    if login_error is not None:
        client.async_login.side_effect = login_error
    client.async_get_virtual_entities.return_value = virtual_entities
    return client


async def test_user_flow_creates_entry(
    glowmarkt_env, hass: HomeAssistant
) -> None:
    """Valid credentials with at least one meter create an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with (
        patch(CLIENT_PATH, return_value=_mock_client()),
        patch("custom_components.glowmarkt.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == USERNAME
    assert result["data"] == {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (GlowmarktAuthError("nope"), "invalid_auth"),
        (GlowmarktConnectionError("down"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors(
    glowmarkt_env, hass: HomeAssistant, error: Exception, expected: str
) -> None:
    """Each failure mode maps to its own message rather than a generic one."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(CLIENT_PATH, return_value=_mock_client(login_error=error)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_user_flow_no_meters(
    glowmarkt_env, hass: HomeAssistant
) -> None:
    """Signing in successfully but with no meters is its own error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(CLIENT_PATH, return_value=_mock_client(virtual_entities=[])):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_meters"}


async def test_duplicate_account_aborts(
    glowmarkt_env, hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The same Bright account cannot be added twice."""
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(CLIENT_PATH, return_value=_mock_client()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password(
    glowmarkt_env, hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Reauth replaces the stored password without creating a second entry."""
    config_entry.add_to_hass(hass)

    result = await config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with (
        patch(CLIENT_PATH, return_value=_mock_client()),
        patch("custom_components.glowmarkt.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-password"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "new-password"
    assert config_entry.data[CONF_USERNAME] == USERNAME


async def test_reauth_rejects_bad_password(
    glowmarkt_env, hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A still-wrong password keeps the form open."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)

    with patch(
        CLIENT_PATH, return_value=_mock_client(login_error=GlowmarktAuthError("nope"))
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "still-wrong"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert config_entry.data[CONF_PASSWORD] == PASSWORD
