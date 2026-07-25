"""Tests for Glowmarkt setup, discovery and sensors."""

from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.glowmarkt.const import DOMAIN

from .const import (
    DAILY_COST,
    DAILY_ENERGY,
    RESOURCES_ELEC_ONLY,
    VIRTUAL_ENTITIES_TWO,
    FakeGlowmarktClient,
)


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, client: FakeGlowmarktClient
) -> None:
    entry.add_to_hass(hass)
    with patch(
        "custom_components.glowmarkt.GlowmarktClient", return_value=client
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_setup_creates_sensors_for_both_fuels(
    glowmarkt_env, hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A dual-fuel account gets four sensors, and reactive power is ignored."""
    client = FakeGlowmarktClient()
    await _setup(hass, config_entry, client)

    assert config_entry.state is ConfigEntryState.LOADED

    entities = [
        eid for eid in hass.states.async_entity_ids("sensor") if "smart_home" in eid
    ]
    assert len(entities) == 4

    # electricity.import.reactive is only meaningful for large non-domestic
    # sites and must never produce an entity.
    assert not any("reactive" in eid for eid in entities)
    assert hass.states.get("sensor.smart_home_electricity_today") is not None
    assert hass.states.get("sensor.smart_home_gas_today") is not None


async def test_energy_and_cost_values(
    glowmarkt_env, hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Energy passes through as kWh; cost converts from pence to pounds."""
    await _setup(hass, config_entry, FakeGlowmarktClient())

    energy = hass.states.get("sensor.smart_home_electricity_today")
    assert float(energy.state) == DAILY_ENERGY

    cost = hass.states.get("sensor.smart_home_electricity_cost_today")
    assert float(cost.state) == DAILY_COST / 100
    assert cost.attributes["unit_of_measurement"] == "GBP"


async def test_sensors_have_no_state_class(
    glowmarkt_env, hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Statistics come from the API import, so entities must not generate them.

    A state_class here would make the recorder produce a second, shorter series
    for the same data.
    """
    await _setup(hass, config_entry, FakeGlowmarktClient())

    state = hass.states.get("sensor.smart_home_electricity_today")
    assert "state_class" not in state.attributes


async def test_statistic_ids_single_installation(
    glowmarkt_env, hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """One installation gets short, readable statistic IDs."""
    client = FakeGlowmarktClient()
    await _setup(hass, config_entry, client)

    ids = {r.statistic_id for r in config_entry.runtime_data.resources}
    assert ids == {
        f"{DOMAIN}:electricity_consumption",
        f"{DOMAIN}:electricity_consumption_cost",
        f"{DOMAIN}:gas_consumption",
        f"{DOMAIN}:gas_consumption_cost",
    }


async def test_statistic_ids_disambiguated_across_installations(
    glowmarkt_env, hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Two installations sharing a classifier get the site name prefixed."""
    client = FakeGlowmarktClient(
        virtual_entities=VIRTUAL_ENTITIES_TWO, resources=RESOURCES_ELEC_ONLY
    )
    await _setup(hass, config_entry, client)

    ids = {r.statistic_id for r in config_entry.runtime_data.resources}
    assert ids == {
        f"{DOMAIN}:smart_home_electricity_consumption",
        f"{DOMAIN}:smart_home_electricity_consumption_cost",
        f"{DOMAIN}:holiday_cottage_electricity_consumption",
        f"{DOMAIN}:holiday_cottage_electricity_consumption_cost",
    }
    # Four resources per site, both sites discovered.
    assert len(config_entry.runtime_data.resources) == 4


async def test_unload(
    glowmarkt_env, hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The entry unloads cleanly."""
    await _setup(hass, config_entry, FakeGlowmarktClient())

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
