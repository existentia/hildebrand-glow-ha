"""Fixtures for the Glowmarkt tests."""

from __future__ import annotations

import logging
from collections.abc import Generator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.glowmarkt.const import DOMAIN

from .const import PASSWORD, USERNAME, FakeGlowmarktClient

# The recorder test fixtures run SQLAlchemy with echo on, which buries the
# actual test output under every INSERT the backfill performs.
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)


@pytest.fixture
def glowmarkt_env(recorder_mock, enable_custom_integrations) -> None:
    """Recorder plus custom-integration loading, in the order pytest-hacc needs.

    `recorder_db_url` asserts that `hass` has not been created yet, and
    `enable_custom_integrations` creates it — so the recorder fixture has to be
    resolved first. Requesting them here in this order pins that down once,
    rather than relying on every test listing its arguments correctly.

    The integration declares `recorder` as a dependency, so even tests that only
    exercise the config flow need the recorder set up.
    """
    return


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A configured Glowmarkt account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=USERNAME,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )


@pytest.fixture
def fake_client() -> FakeGlowmarktClient:
    """A dual-fuel account by default."""
    return FakeGlowmarktClient()


@pytest.fixture
def patch_client(fake_client: FakeGlowmarktClient) -> Generator[FakeGlowmarktClient]:
    """Swap the real API client for the fake one during setup."""
    with patch(
        "custom_components.glowmarkt.GlowmarktClient", return_value=fake_client
    ):
        yield fake_client
