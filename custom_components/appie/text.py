"""Search field for the dashboard: typing a term searches AH."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import AppieError
from .coordinator import AppieConfigEntry
from .entity import device_info

# As many results as appie.search gives by default.
SEARCH_COUNT = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([SearchText(entry)])


class SearchText(TextEntity):
    """Set a search term: AH is searched and sensor.albert_heijn_zoekresultaat shows the products."""

    _attr_has_entity_name = True
    _attr_name = "Zoeken"
    _attr_icon = "mdi:magnify"
    _attr_native_max = 100

    def __init__(self, entry: AppieConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_zoeken"
        self._attr_device_info = device_info(entry)
        self._attr_native_value = ""

    async def async_set_value(self, value: str) -> None:
        data = self._entry.runtime_data
        value = value.strip()
        if value:
            try:
                await data.search.async_search(data.client, value, SEARCH_COUNT)
            except AppieError as err:
                raise HomeAssistantError(f"Albert Heijn: {err}") from err
        self._attr_native_value = value
        self.async_write_ha_state()
