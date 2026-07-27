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


async def test_uncollected_zero_tail_is_not_imported(
    glowmarkt_env, hass: HomeAssistant
) -> None:
    """Trailing zeroes mean "not collected yet", so they must not be stored.

    Importing them bakes a zero into the cumulative sum, and because the
    incremental pass only walks forward the real reading would never replace
    it — the meter would appear to stop, permanently.
    """
    zero_from = dt_util.utcnow().replace(
        minute=0, second=0, microsecond=0
    ) - timedelta(hours=5)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="a@b.com",
        data={"username": "a@b.com", "password": "pw"},
        options={CONF_BACKFILL_DAYS: 2},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.glowmarkt.GlowmarktClient",
        return_value=FakeGlowmarktClient(zero_from=zero_from),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    rows = await _rows(hass)
    assert rows

    assert not any(row["state"] == 0 for row in rows), "stored an uncollected hour"
    latest = dt_util.utc_from_timestamp(rows[-1]["start"])
    assert latest < zero_from


async def test_late_data_replaces_previously_zero_hours(
    glowmarkt_env, hass: HomeAssistant
) -> None:
    """Readings that arrive late overwrite what was already stored.

    The trailing window is re-imported on every pass precisely so a stalled
    feed repairs itself once the data lands.
    """
    now_hour = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    zero_from = now_hour - timedelta(hours=5)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="a@b.com",
        data={"username": "a@b.com", "password": "pw"},
        options={CONF_BACKFILL_DAYS: 2},
    )
    entry.add_to_hass(hass)
    stalled = FakeGlowmarktClient(zero_from=zero_from)
    with patch("custom_components.glowmarkt.GlowmarktClient", return_value=stalled):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    before = await _rows(hass)
    stalled_latest = dt_util.utc_from_timestamp(before[-1]["start"])

    # The DCC catches up and the missing hours now return real values.
    stalled.zero_from = None
    await entry.runtime_data.async_backfill()
    await async_wait_recording_done(hass)

    after = await _rows(hass)
    assert dt_util.utc_from_timestamp(after[-1]["start"]) > stalled_latest
    assert all(row["state"] == HOURLY_ENERGY for row in after)
    # Sums stay monotonic across the repaired window.
    sums = [row["sum"] for row in after]
    assert sums == sorted(sums)


async def test_catchup_is_requested_and_rate_limited(
    glowmarkt_env, hass: HomeAssistant
) -> None:
    """Each resource gets a DCC catchup, but not on every single poll."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="a@b.com",
        data={"username": "a@b.com", "password": "pw"},
        options={CONF_BACKFILL_DAYS: 1},
    )
    client = await _setup(hass, entry)

    resource_count = len(entry.runtime_data.resources)
    assert sorted(client.catchup_calls) == sorted(
        r.resource_id for r in entry.runtime_data.resources
    )

    # A refresh straight afterwards is inside the two-hour limit.
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert len(client.catchup_calls) == resource_count
