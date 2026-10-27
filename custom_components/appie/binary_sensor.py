"""Whether the favorite store is open right now."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import AppieConfigEntry, StoreCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([StoreOpenSensor(entry, entry.runtime_data.store)])


class StoreOpenSensor(CoordinatorEntity[StoreCoordinator], BinarySensorEntity):
    """Open or closed, worked out locally from the opening hours every minute."""

    _attr_has_entity_name = True
    _attr_name = "Winkel open"
    _attr_icon = "mdi:store-clock"

    def __init__(self, entry: AppieConfigEntry, coordinator: StoreCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_winkel_open"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))

    @callback
    def _tick(self, _now) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def is_on(self) -> bool | None:
        store = self.coordinator.data
        return store.is_open(dt_util.now()) if store else None
