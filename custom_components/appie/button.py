"""Buttons that put a product we often buy on the shopping list."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AppieError
from .coordinator import AppieConfigEntry, FavoritesCoordinator, ListCoordinator
from .entity import device_info
from .models import Favorite, favorite_attributes


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    count = entry.runtime_data.favorites.count
    _remove_surplus_buttons(hass, entry, count)
    async_add_entities(FavoriteButton(entry, rank) for rank in range(1, count + 1))


def _remove_surplus_buttons(hass: HomeAssistant, entry: AppieConfigEntry, count: int) -> None:
    """Drop the buttons above the configured count (after lowering it)."""
    registry = er.async_get(hass)
    prefix = f"{entry.unique_id}_vaak_gekocht_"
    for reg in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg.domain != "button" or not reg.unique_id.startswith(prefix):
            continue
        rank = reg.unique_id.removeprefix(prefix)
        if rank.isdigit() and int(rank) > count:
            registry.async_remove(reg.entity_id)


class FavoriteButton(CoordinatorEntity[FavoritesCoordinator], ButtonEntity):
    """Rank N of the most bought products; pressing adds it to the list."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:cart-plus"

    def __init__(self, entry: AppieConfigEntry, rank: int) -> None:
        super().__init__(entry.runtime_data.favorites)
        self._list: ListCoordinator = entry.runtime_data.shopping_list
        self._rank = rank
        self._attr_unique_id = f"{entry.unique_id}_vaak_gekocht_{rank}"
        # Fixed entity ids; the name follows whatever product holds this rank.
        self.entity_id = f"button.albert_heijn_vaak_gekocht_{rank}"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # on_list / quantity_on_list follow the shopping list.
        self.async_on_remove(self._list.async_add_listener(self.async_write_ha_state))

    @property
    def _favorite(self) -> Favorite | None:
        favorites = self.coordinator.data or []
        return favorites[self._rank - 1] if len(favorites) >= self._rank else None

    @property
    def available(self) -> bool:
        return super().available and self._favorite is not None

    @property
    def name(self) -> str:
        favorite = self._favorite
        return favorite.title if favorite else f"Vaak gekocht {self._rank}"

    @property
    def entity_picture(self) -> str | None:
        favorite = self._favorite
        return favorite.image if favorite else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        favorite = self._favorite
        if favorite is None:
            return {"rank": self._rank}
        return favorite_attributes(favorite, self._list.data or [])

    async def async_press(self) -> None:
        favorite = self._favorite
        if favorite is None:
            raise HomeAssistantError("Er staat (nog) geen product op deze plek")
        wanted = favorite.as_list_item()
        current = next((i for i in self._list.data or [] if i.key == wanted.key), None)
        if current is None:
            body = wanted.patch()
        elif current.checked:
            # Ticked off earlier: put it back as a fresh item.
            body = current.patch(quantity=1, checked=False)
        else:
            body = current.patch(quantity=current.quantity + 1)
        try:
            await self._list.client.patch_list([body])
        except AppieError as err:
            raise HomeAssistantError(f"Albert Heijn: {err}") from err
        await self._list.async_refresh()
