"""Tests for the long-term statistics backfill.

This is the part that has no equivalent in the older Glow integrations, and the
part most likely to break quietly, so it is tested against a real recorder.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.glowmarkt.const import CONF_BACKFILL_DAYS, DOMAIN

from .const import HOURLY_ENERGY, FakeGlowmarktClient

STAT_ID = f"{DOMAIN}:electricity_consumption"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> FakeGlowmarktClient:
    client = FakeGlowmarktClient()
    entry.add_to_hass(hass)
    with patch("custom_components.glowmarkt.GlowmarktClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    return client


async def _rows(hass: HomeAssistant, stat_id: str = STAT_ID) -> list[dict]:
    """Read back every imported statistic for a series."""
    start = dt_util.utcnow() - timedelta(days=400)
    stats = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        None,
        {stat_id},
        "hour",
        None,
        {"state", "sum"},
    )
    return stats.get(stat_id, [])


async def test_backfill_imports_hourly_statistics(
    glowmarkt_env, hass: HomeAssistant
) -> None:
    """Setting up imports history rather than starting from zero."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="a@b.com",
        data={"username": "a@b.com", "password": "pw"},
        options={CONF_BACKFILL_DAYS: 2},
    )
    await _setup(hass, entry)

    rows = await _rows(hass)
    assert rows, "no statistics were imported"

    # Two days of hourly data, minus the hour still in progress.
    assert 44 <= len(rows) <= 49

    earliest = dt_util.utc_from_timestamp(rows[0]["start"])
    assert earliest >= dt_util.utcnow() - timedelta(days=2, hours=1)

    # sum is cumulative, so the last row carries the running total.
    assert rows[0]["state"] == HOURLY_ENERGY
    assert rows[-1]["sum"] > rows[0]["sum"]


async def test_increasing_depth_rebuilds_the_series(
    glowmarkt_env, hass: HomeAssistant
) -> None:
    """Raising the history depth reaches further back instead of doing nothing.

    The incremental path only ever walks forward, so a deeper window requires
    the series to be cleared and rebuilt.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="a@b.com",
        data={"username": "a@b.com", "password": "pw"},
        options={CONF_BACKFILL_DAYS: 1},
    )
    await _setup(hass, entry)

    shallow = await _rows(hass)
    assert shallow
    shallow_earliest = dt_util.utc_from_timestamp(shallow[0]["start"])

    # Ask for more history; the update listener reloads the entry.
    with patch(
        "custom_components.glowmarkt.GlowmarktClient",
        return_value=FakeGlowmarktClient(),
    ):
        hass.config_entries.async_update_entry(entry, options={CONF_BACKFILL_DAYS: 4})
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    deep = await _rows(hass)
    deep_earliest = dt_util.utc_from_timestamp(deep[0]["start"])

    assert deep_earliest < shallow_earliest
    assert len(deep) > len(shallow)
    # Rebuilt from scratch, so the running sum restarts rather than continuing
    # on from the shallow series.
    assert deep[0]["sum"] == HOURLY_ENERGY


async def test_second_pass_does_not_duplicate(
    glowmarkt_env, hass: HomeAssistant
) -> None:
    """Re-running the backfill at the same depth imports nothing new."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="a@b.com",
        data={"username": "a@b.com", "password": "pw"},
        options={CONF_BACKFILL_DAYS: 2},
    )
    await _setup(hass, entry)
    first = await _rows(hass)

    await entry.runtime_data.async_backfill()
    await async_wait_recording_done(hass)

    assert len(await _rows(hass)) == len(first)
