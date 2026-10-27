"""Bonus, receipt and "vaak gekocht" sensors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import (
    AppieConfigEntry,
    BonusCoordinator,
    FavoritesCoordinator,
    ListCostCoordinator,
    ReceiptsCoordinator,
)
from .entity import device_info
from .models import SOURCE_PERSONAL, favorite_attributes

RECENT_RECEIPTS = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    async_add_entities(
        [
            BonusSensor(entry, data.bonus),
            LatestReceiptSensor(entry, data.receipts),
            MonthSpendSensor(entry, data.receipts),
            FavoritesSensor(entry, data.favorites),
            ListCostSensor(entry, data.list_cost),
        ]
    )


class _Base(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, entry: AppieConfigEntry, coordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_name = name
        self._attr_device_info = device_info(entry)


class BonusSensor(_Base, SensorEntity):
    """Number of relevant bonus offers; the offers themselves as attribute."""

    _attr_icon = "mdi:sale"
    _attr_native_unit_of_measurement = "aanbiedingen"
    # The offer list is big and changes weekly; keep it out of the database.
    _unrecorded_attributes = frozenset({"offers"})

    def __init__(self, entry: AppieConfigEntry, coordinator: BonusCoordinator) -> None:
        super().__init__(entry, coordinator, "bonus_voor_ons", "Bonus voor ons")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.offers)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "period_start": data.period_start,
            "period_end": data.period_end,
            "on_list": sum(o.on_list for o in data.offers),
            "personal": sum(o.source == SOURCE_PERSONAL for o in data.offers),
            "offers": [o.as_dict() for o in data.offers],
        }


class LatestReceiptSensor(_Base, SensorEntity):
    """Total of the most recent in-store receipt."""

    _attr_icon = "mdi:receipt-text"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _unrecorded_attributes = frozenset({"items", "discounts", "recent"})

    def __init__(self, entry: AppieConfigEntry, coordinator: ReceiptsCoordinator) -> None:
        super().__init__(entry, coordinator, "laatste_kassabon", "Laatste kassabon")

    @property
    def native_value(self) -> float | None:
        latest = self.coordinator.data.latest
        return latest.total if latest else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        detail = data.latest_detail
        return {
            "datetime": data.latest.local(dt_util.get_default_time_zone()).isoformat() if data.latest else None,
            "items": detail.items if detail else [],
            "discounts": detail.discounts if detail else [],
            "discount_total": detail.discount_total if detail else None,
            "payments": detail.payments if detail else [],
            "recent": [
                {"datetime": r.local(dt_util.get_default_time_zone()).isoformat(), "total": r.total}
                for r in data.receipts[:RECENT_RECEIPTS]
            ],
        }


class MonthSpendSensor(_Base, SensorEntity):
    """Sum of this month's receipts; resets on the 1st."""

    _attr_icon = "mdi:cart-outline"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"

    def __init__(self, entry: AppieConfigEntry, coordinator: ReceiptsCoordinator) -> None:
        super().__init__(entry, coordinator, "uitgaven_deze_maand", "Uitgaven deze maand")

    @property
    def native_value(self) -> float:
        return self.coordinator.data.month_total

    @property
    def last_reset(self) -> datetime:
        return dt_util.start_of_local_day(dt_util.now().replace(day=1))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"receipts": self.coordinator.data.month_count}


class FavoritesSensor(_Base, SensorEntity):
    """The whole "vaak gekocht" ranking in one entity, for dashboards."""

    _attr_icon = "mdi:star-shopping"
    _attr_native_unit_of_measurement = "producten"
    _unrecorded_attributes = frozenset({"producten"})

    def __init__(self, entry: AppieConfigEntry, coordinator: FavoritesCoordinator) -> None:
        super().__init__(entry, coordinator, "vaak_gekocht", "Vaak gekocht")
        self._list = entry.runtime_data.shopping_list

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # on_list / quantity_on_list follow the shopping list.
        self.async_on_remove(self._list.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        items = self._list.data or []
        return {
            "producten": [
                {**favorite_attributes(f, items), "entity_picture": f.image} for f in self.coordinator.data or []
            ]
        }


class ListCostSensor(_Base, SensorEntity):
    """What the products on the list cost, after bonus discount."""

    _attr_icon = "mdi:cart-variant"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"

    def __init__(self, entry: AppieConfigEntry, coordinator: ListCostCoordinator) -> None:
        super().__init__(entry, coordinator, "lijst_kosten", "Lijst kosten")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.total if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cost = self.coordinator.data
        if cost is None:
            return {}
        return {
            "zonder_korting": cost.without_discount,
            "korting": cost.discount,
            "aantal_producten": cost.products,
            "aantal_vrije_tekst": cost.free_text,
        }
