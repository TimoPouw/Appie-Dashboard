"""Bonus, receipt, list, store and "vaak gekocht" sensors."""

from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import asdict
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import (
    AppieConfigEntry,
    BargainsCoordinator,
    BonusBoxCoordinator,
    BonusCoordinator,
    DontForgetCoordinator,
    FavoriteListsCoordinator,
    FavoritesCoordinator,
    ListCostCoordinator,
    ReceiptsCoordinator,
    ReceiptViewerCoordinator,
    SpotlightCoordinator,
    StoreCoordinator,
)
from .entity import device_info
from .models import SOURCE_PERSONAL, favorite_attributes, open_products, receipt_view

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
            DontForgetSensor(entry, data.dont_forget),
            StoreSensor(entry, data.store),
            BargainsSensor(entry, data.bargains),
            PickedReceiptSensor(entry, data.receipt_viewer),
            SpotlightSensor(entry, data.spotlight),
            BonusBoxSensor(entry, data.bonus_box),
            FavoriteListsSensor(entry, data.favorite_lists),
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
        self._viewer = entry.runtime_data.receipt_viewer

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
                {
                    "datetime": r.local(dt_util.get_default_time_zone()).isoformat(),
                    "total": r.total,
                    "id": r.id,
                    "pdf_url": self._viewer.pdf_url(r.id),
                }
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


class DontForgetSensor(_Base, SensorEntity):
    """Suggestions from the app's "vergeet niet" lane."""

    _attr_icon = "mdi:lightbulb-on-outline"
    _attr_native_unit_of_measurement = "suggesties"
    _unrecorded_attributes = frozenset({"suggesties"})

    def __init__(self, entry: AppieConfigEntry, coordinator: DontForgetCoordinator) -> None:
        super().__init__(entry, coordinator, "vergeet_niet", "Vergeet niet")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"suggesties": [asdict(s) for s in self.coordinator.data or []]}


STATE_CLOSED = "gesloten"


class StoreSensor(_Base, SensorEntity):
    """Today's closing time of the favorite store, or "gesloten"."""

    _attr_icon = "mdi:store"

    def __init__(self, entry: AppieConfigEntry, coordinator: StoreCoordinator) -> None:
        super().__init__(entry, coordinator, "winkel", "Winkel")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Flips to "gesloten" at closing time without asking AH.
        self.async_on_remove(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))

    @callback
    def _tick(self, _now) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def native_value(self) -> str | None:
        store = self.coordinator.data
        if store is None:
            return None
        return store.closing_time(dt_util.now()) or STATE_CLOSED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        store = self.coordinator.data
        if store is None:
            return {}
        return {
            "store_id": store.id,
            "adres": store.address,
            "openingstijden": store.upcoming(dt_util.now()),
            "services": store.services,
        }


class BargainsSensor(_Base, SensorEntity):
    """Koopjes (last-chance markdowns) in the favorite store."""

    _attr_icon = "mdi:tag-heart"
    _attr_native_unit_of_measurement = "koopjes"
    _unrecorded_attributes = frozenset({"items"})

    def __init__(self, entry: AppieConfigEntry, coordinator: BargainsCoordinator) -> None:
        super().__init__(entry, coordinator, "koopjes", "Koopjes")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # is_favoriet follows the "vaak gekocht" ranking.
        self.async_on_remove(self.coordinator.favorites.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        favorites = self.coordinator.favorite_ids()
        return {
            "items": [
                {
                    "product_id": b.product_id,
                    "title": b.title,
                    "size": b.size,
                    "category": b.category,
                    "markdown_type": b.markdown_type,
                    "expires": b.expires,
                    "is_favoriet": b.product_id in favorites,
                    "price": b.price,
                    "price_was": b.price_was,
                    "percentage": b.percentage,
                }
                for b in self.coordinator.data or []
            ]
        }


class PickedReceiptSensor(_Base, SensorEntity):
    """The receipt picked in select.albert_heijn_kassabon, with its lines."""

    _attr_icon = "mdi:receipt-text-check"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    # Looked at, not kept: none of it goes into the database.
    _unrecorded_attributes = frozenset(
        {"receipt_id", "datetime", "items", "discounts", "discount_total", "payments", "pdf_url"}
    )

    def __init__(self, entry: AppieConfigEntry, coordinator: ReceiptViewerCoordinator) -> None:
        super().__init__(entry, coordinator, "gekozen_kassabon", "Gekozen kassabon")

    @property
    def native_value(self) -> float | None:
        viewed = self.coordinator.data
        return viewed.receipt.total if viewed else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        viewed = self.coordinator.data
        if viewed is None:
            return {}
        view = receipt_view(viewed.receipt, viewed.detail, dt_util.get_default_time_zone())
        view.pop("total")
        return {**view, "pdf_url": self.coordinator.pdf_url(viewed.receipt.id)}


class SpotlightSensor(_Base, SensorEntity):
    """The week's highlighted bonus; on_list follows the shopping list."""

    _attr_icon = "mdi:star-circle"
    _attr_native_unit_of_measurement = "aanbiedingen"
    _unrecorded_attributes = frozenset({"offers"})

    def __init__(self, entry: AppieConfigEntry, coordinator: SpotlightCoordinator) -> None:
        super().__init__(entry, coordinator, "bonus_spotlight", "Bonus spotlight")
        self._list = entry.runtime_data.shopping_list

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._list.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        on_list = {i.product_id for i in open_products(self._list.data or [])}
        return {
            "offers": [
                {**o.as_dict(), "on_list": bool(on_list.intersection(o.product_ids))}
                for o in self.coordinator.data or []
            ]
        }


class BonusBoxSensor(_Base, SensorEntity):
    """Personal Bonus Box: how many offers, which are activated."""

    _attr_icon = "mdi:gift-outline"
    _attr_native_unit_of_measurement = "aanbiedingen"
    _unrecorded_attributes = frozenset({"aanbiedingen"})

    def __init__(self, entry: AppieConfigEntry, coordinator: BonusBoxCoordinator) -> None:
        super().__init__(entry, coordinator, "bonus_box", "Bonus Box")

    @property
    def native_value(self) -> int | None:
        box = self.coordinator.data
        return len(box.offers) if box else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        box = self.coordinator.data
        if box is None:
            return {}
        return {"max_activaties": box.max_activations, "geactiveerd": box.activated, "aanbiedingen": box.offers}


class FavoriteListsSensor(_Base, SensorEntity):
    """The favorite lists ("lijstjes") in the app."""

    _attr_icon = "mdi:format-list-checks"
    _attr_native_unit_of_measurement = "lijsten"

    def __init__(self, entry: AppieConfigEntry, coordinator: FavoriteListsCoordinator) -> None:
        super().__init__(entry, coordinator, "favoriete_lijsten", "Favoriete lijsten")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"lijsten": [asdict(fl) for fl in self.coordinator.data or []]}
