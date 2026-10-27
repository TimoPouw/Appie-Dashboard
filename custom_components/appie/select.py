"""Pick a recent receipt to look at."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import AppieConfigEntry, ReceiptViewerCoordinator
from .entity import device_info
from .models import receipt_label


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ReceiptSelect(entry, entry.runtime_data.receipt_viewer)])


class ReceiptSelect(CoordinatorEntity[ReceiptViewerCoordinator], SelectEntity):
    """The recent receipts; picking one fetches it for the receipt sensor."""

    _attr_has_entity_name = True
    _attr_name = "Kassabon"
    _attr_icon = "mdi:receipt-text-outline"

    def __init__(self, entry: AppieConfigEntry, coordinator: ReceiptViewerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_kassabon"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # New receipts become new options.
        self.async_on_remove(self.coordinator.receipts.async_add_listener(self.async_write_ha_state))

    @property
    def _labels(self) -> dict[str, str]:
        """Label -> receipt id, newest first."""
        data = self.coordinator.receipts.data
        tz = dt_util.get_default_time_zone()
        labels: dict[str, str] = {}
        for receipt in data.receipts if data else []:
            label = receipt_label(receipt, tz)
            if label in labels:
                label = f"{label} ({receipt.id[-4:]})"
            labels[label] = receipt.id
        return labels

    @property
    def options(self) -> list[str]:
        return list(self._labels)

    @property
    def current_option(self) -> str | None:
        viewed = self.coordinator.data
        if viewed is None:
            return None
        return next((label for label, rid in self._labels.items() if rid == viewed.receipt.id), None)

    async def async_select_option(self, option: str) -> None:
        receipt_id = self._labels.get(option)
        if receipt_id is None:
            raise HomeAssistantError(f"Onbekende kassabon: {option}")
        await self.coordinator.async_select(receipt_id)
        if not self.coordinator.last_update_success:
            raise HomeAssistantError(f"Albert Heijn: {self.coordinator.last_exception}")
