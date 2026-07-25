"""Sensor entities for Glowmarkt.

These deliberately carry no state_class. Long-term statistics for these streams
are imported directly from the Glowmarkt API as external statistics (see
coordinator.py), which lets history be backfilled rather than only accumulating
from the moment the integration is installed. Giving the entities a state_class
as well would have the recorder generate a second, shorter set of statistics for
the same data.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GlowmarktConfigEntry
from .const import CURRENCY_GBP, DOMAIN
from .coordinator import GlowmarktCoordinator, GlowmarktResource


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GlowmarktConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Glowmarkt sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        GlowmarktTodaySensor(coordinator, resource)
        for resource in coordinator.resources
    )


class GlowmarktTodaySensor(CoordinatorEntity[GlowmarktCoordinator], SensorEntity):
    """Today's running total for one Glowmarkt resource."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: GlowmarktCoordinator, resource: GlowmarktResource
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._resource = resource

        self._attr_unique_id = f"{resource.resource_id}_today"
        self._attr_name = f"{resource.info.label} today"
        self._attr_icon = resource.info.icon

        if resource.info.is_cost:
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_native_unit_of_measurement = CURRENCY_GBP
            self._attr_suggested_display_precision = 2
        else:
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
            self._attr_suggested_display_precision = 3

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, resource.ve_id)},
            name=resource.ve_name,
            manufacturer="Hildebrand Glow",
            model="Glowmarkt / Bright",
            entry_type=None,
        )

    @property
    def native_value(self) -> float | None:
        """Return today's total so far."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._resource.resource_id)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose the statistic ID so the Energy dashboard is easy to wire up."""
        return {
            "statistic_id": self._resource.statistic_id,
            "classifier": self._resource.classifier,
        }

    @property
    def available(self) -> bool:
        """Available when the coordinator has data for this resource."""
        return (
            super().available
            and self.coordinator.data is not None
            and self._resource.resource_id in self.coordinator.data
        )
