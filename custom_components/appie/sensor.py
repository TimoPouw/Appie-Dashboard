"""Bonus, receipt, list, store and "vaak gekocht" sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
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
    SavingsCoordinator,
    SpotlightCoordinator,
    StoreCoordinator,
)
from .const import DOMAIN
from .entity import device_info
from .models import SOURCE_PERSONAL, favorite_attributes, missed_bonus, open_products, receipt_view

RECENT_RECEIPTS = 10
# Sensors that existed in an earlier version and are gone now.
REMOVED_KEYS = ("openstaand_tegoed",)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    registry = er.async_get(hass)
    for key in REMOVED_KEYS:
        if entity_id := registry.async_get_entity_id("sensor", DOMAIN, f"{entry.unique_id}_{key}"):
            registry.async_remove(entity_id)
    async_add_entities(
        [
            BonusSensor(entry, data.bonus),
            LatestReceiptSensor(entry, data.receipts),
            MonthSpendSensor(entry, data.receipts),
            FavoritesSensor(entry, data.favorites),
            ListCostSensor(entry, data.list_cost),
            DontForgetSensor(entry, data.dont_forget),
            StoreSensor(entry, data.store),
            StoreHoursSensor(entry, data.store, "winkel_open_vanaf", "Winkel open vanaf", 0),
            StoreHoursSensor(entry, data.store, "winkel_open_tot", "Winkel open tot", 1),
            BargainsSensor(entry, data.bargains),
            PickedReceiptSensor(entry, data.receipt_viewer),
            SpotlightSensor(entry, data.spotlight),
            BonusBoxSensor(entry, data.bonus_box),
            FavoriteListsSensor(entry, data.favorite_lists),
            MissedBonusSensor(entry, data.favorites),
            *(SavingsSensor(entry, data.savings, description) for description in SAVINGS_SENSORS),
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
    _unrecorded_attributes = frozenset({"per_maand"})

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
        return {"receipts": self.coordinator.data.month_count, "per_maand": self.coordinator.data.per_month}


class FavoritesSensor(_Base, SensorEntity):
    """The whole "vaak gekocht" ranking in one entity, for dashboards."""

    _attr_icon = "mdi:cart-heart"
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


class StoreHoursSensor(_Base, SensorEntity):
    """Today's opening (index 0) or closing (index 1) time, or "gesloten"."""

    _attr_icon = "mdi:clock-outline"

    def __init__(self, entry: AppieConfigEntry, coordinator: StoreCoordinator, key: str, name: str, index: int) -> None:
        super().__init__(entry, coordinator, key, name)
        self._index = index

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The day changes at midnight without a new fetch.
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
        hours = store.hours_today(dt_util.now())
        return hours[self._index] if hours else STATE_CLOSED


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


class MissedBonusSensor(_Base, SensorEntity):
    """Products we buy often that are in the bonus now, but not on the list."""

    _attr_icon = "mdi:sale-outline"
    _attr_native_unit_of_measurement = "producten"
    _unrecorded_attributes = frozenset({"producten"})

    def __init__(self, entry: AppieConfigEntry, coordinator: FavoritesCoordinator) -> None:
        super().__init__(entry, coordinator, "gemiste_bonus", "Gemiste bonus")
        self._list = entry.runtime_data.shopping_list

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._list.async_add_listener(self.async_write_ha_state))

    def _products(self) -> list[dict[str, Any]]:
        return missed_bonus(self.coordinator.data or [], self._list.data or [])

    @property
    def native_value(self) -> int:
        return len(self._products())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"producten": self._products()}


@dataclass(frozen=True, kw_only=True)
class SavingsDescription:
    """One savings sensor: which part of Savings it shows, and how."""

    key: str
    name: str
    icon: str
    part: str
    value: Callable[[Any], Any]
    attributes: Callable[[Any], dict[str, Any]] = lambda part: {}
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    options: list[str] | None = None


def _stamps_value(stamps: dict) -> float | None:
    if stamps.get("uitbetaling") is not None:
        return stamps["uitbetaling"]
    if stamps.get("ingelegd") is None:
        return None
    return round(stamps["ingelegd"] + (stamps.get("rente") or 0), 2)


SAVINGS_SENSORS = (
    SavingsDescription(
        key="koopzegels",
        name="Koopzegels",
        icon="mdi:ticket-percent",
        part="stamps",
        unit="zegels",
        value=lambda s: s.get("zegels"),
        attributes=lambda s: {k: v for k, v in s.items() if k != "zegels"},
    ),
    SavingsDescription(
        key="koopzegels_waarde",
        name="Koopzegels waarde",
        icon="mdi:piggy-bank",
        part="stamps",
        unit="EUR",
        device_class=SensorDeviceClass.MONETARY,
        value=_stamps_value,
    ),
    SavingsDescription(
        key="air_miles",
        name="Air Miles",
        icon="mdi:airplane",
        part="miles",
        unit="Air Miles",
        value=lambda m: m.get("saldo"),
        attributes=lambda m: {"fout": m.get("fout")},
    ),
    SavingsDescription(
        key="spaaracties",
        name="Spaaracties",
        icon="mdi:star-shooting",
        part="programs",
        unit="acties",
        value=len,
        attributes=lambda p: {"met_punten": sum(bool(a.get("punten")) for a in p), "acties": p},
    ),
    SavingsDescription(
        key="uitdagingen",
        name="Uitdagingen",
        icon="mdi:flag-checkered",
        part="challenges",
        unit="uitdagingen",
        value=lambda c: sum(not u["afgelopen"] for u in c),
        attributes=lambda c: {"uitdagingen": c},
    ),
    SavingsDescription(
        key="premium",
        name="Premium",
        icon="mdi:crown",
        part="premium",
        device_class=SensorDeviceClass.ENUM,
        options=["actief", "niet actief"],
        value=lambda p: "actief" if p.get("actief") else "niet actief",
        attributes=lambda p: {k: v for k, v in p.items() if k != "actief"},
    ),
    SavingsDescription(
        key="premium_besparing",
        name="Premium besparing",
        icon="mdi:cash-check",
        part="premium",
        unit="EUR",
        device_class=SensorDeviceClass.MONETARY,
        # With Premium: what it saves you; without: what it would, per AH's estimate.
        value=lambda p: p.get("besparing_per_jaar"),
        attributes=lambda p: {
            "actief": p.get("actief"),
            "besparing_rest_periode": p.get("besparing_rest_periode"),
            "besparing_per_dag": p.get("besparing_per_dag"),
            "zegels_per_jaar": p.get("zegels_per_jaar"),
        },
    ),
    SavingsDescription(
        key="premium_bespaard",
        name="Premium bespaard",
        icon="mdi:crown-circle",
        part="premium",
        unit="EUR",
        device_class=SensorDeviceClass.MONETARY,
        # What Premium saved you since you have it, as AH counts it.
        value=lambda p: p.get("totaal_bespaard"),
        attributes=lambda p: {
            "lid_sinds": p.get("lid_sinds"),
            "bespaard_bonus_box": p.get("bespaard_bonus_box"),
            "bespaard_bio": p.get("bespaard_bio"),
            "extra_koopzegels": p.get("extra_koopzegels"),
            "extra_air_miles": p.get("extra_air_miles"),
            "bijgewerkt": p.get("bijgewerkt"),
        },
    ),
    SavingsDescription(
        key="cadeaukaarten",
        name="Cadeaukaarten",
        icon="mdi:wallet-giftcard",
        part="gift_cards",
        unit="EUR",
        device_class=SensorDeviceClass.MONETARY,
        value=lambda c: round(sum(k.get("saldo") or 0 for k in c), 2),
        attributes=lambda c: {"aantal": len(c), "kaarten": c},
    ),
)


class SavingsSensor(_Base, SensorEntity):
    """One part of SavingsCoordinator; unavailable while AH doesn't give it."""

    # Lists that change with every receipt; keep them out of the database.
    _unrecorded_attributes = frozenset({"acties", "uitdagingen", "kaarten"})

    def __init__(self, entry: AppieConfigEntry, coordinator: SavingsCoordinator, description: SavingsDescription) -> None:
        super().__init__(entry, coordinator, description.key, description.name)
        self._description = description
        self._attr_icon = description.icon
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = description.device_class
        self._attr_options = description.options

    def _part(self) -> Any:
        data = self.coordinator.data
        return getattr(data, self._description.part) if data else None

    @property
    def available(self) -> bool:
        return super().available and self._part() is not None

    @property
    def native_value(self) -> Any:
        part = self._part()
        return self._description.value(part) if part is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        part = self._part()
        return self._description.attributes(part) if part is not None else {}
