"""Favorite store, opening hours and koopjes."""

import pytest
from pytest_homeassistant_custom_component.common import async_capture_events, async_fire_time_changed

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.appie.diagnostics import async_get_config_entry_diagnostics
from custom_components.appie.models import parse_store

from .common import STORE, setup_appie

# Tuesday 27 October 2026, 12:00 in Amsterdam; LATE is 22:30, within the 12 h store interval.
OPEN = "2026-10-27T11:00:00+00:00"
LATE = "2026-10-27T22:30:00+00:00"


@pytest.fixture
async def amsterdam(hass: HomeAssistant, freezer):
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to(OPEN)
    return freezer


async def _tick(hass: HomeAssistant, freezer, when: str) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_store_entities(hass: HomeAssistant, api, amsterdam) -> None:
    await setup_appie(hass)
    assert hass.states.get("binary_sensor.albert_heijn_winkel_open").state == "on"
    store = hass.states.get("sensor.albert_heijn_winkel")
    assert store.state == "22:00"
    assert store.attributes["store_id"] == 1527
    assert store.attributes["adres"] == "Nachtegaalstraat 48, 3581AD Utrecht"
    assert store.attributes["services"] == ["PICKUP", "SELFSERVICE"]
    assert store.attributes["openingstijden"] == [
        {"datum": "2026-10-27", "dag": "dinsdag", "open": "08:00", "dicht": "22:00"},
        {"datum": "2026-10-28", "dag": "woensdag", "open": "08:00", "dicht": "00:00"},
        {"datum": "2026-10-29", "dag": "donderdag", "open": None, "dicht": None},
    ]

    # After closing time, without asking AH again.
    calls = api["get_favorite_store"].await_count
    await _tick(hass, amsterdam, LATE)
    assert hass.states.get("binary_sensor.albert_heijn_winkel_open").state == "off"
    assert hass.states.get("sensor.albert_heijn_winkel").state == "gesloten"
    assert api["get_favorite_store"].await_count == calls


def test_opening_hours_edge_cases() -> None:
    store = parse_store(STORE)
    tz = dt_util.get_time_zone("Europe/Amsterdam")
    wednesday_late = dt_util.parse_datetime("2026-10-28T23:30:00").replace(tzinfo=tz)
    # Closing at "00:00" means midnight, not this morning.
    assert store.is_open(wednesday_late)
    assert store.closing_time(wednesday_late) == "00:00"
    thursday = dt_util.parse_datetime("2026-10-29T12:00:00").replace(tzinfo=tz)
    assert not store.is_open(thursday) and store.closing_time(thursday) is None
    early = dt_util.parse_datetime("2026-10-27T07:00:00").replace(tzinfo=tz)
    assert not store.is_open(early) and store.closing_time(early) == "22:00"
    assert parse_store({"data": {"storesFavouriteStore": None}}) is None


async def test_bargains_and_favorite_event(hass: HomeAssistant, api, amsterdam) -> None:
    events = async_capture_events(hass, "appie_koopje_favoriet")
    entry = await setup_appie(hass)
    await hass.async_block_till_done()
    api["get_bargains"].assert_awaited_with(1527)

    state = hass.states.get("sensor.albert_heijn_koopjes")
    assert state.state == "2"
    fish, butter = state.attributes["items"]
    assert fish == {
        "product_id": 12345, "title": "AH Roodbaarsfilet", "size": "ca. 200 g", "category": "Vis",
        "markdown_type": "PERCENTAGE", "expires": "2026-10-28", "is_favoriet": False,
        "price": 3.89, "price_was": 5.99, "percentage": 35.0,
    }
    assert butter["is_favoriet"] is True

    # The butter is in "vaak gekocht": announced once.
    assert len(events) == 1
    assert events[0].data["product_id"] == 111 and events[0].data["title"] == "AH Roomboter"
    assert events[0].data["store_id"] == 1527

    # Next poll: same koopje, no new event.
    await entry.runtime_data.bargains.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1

    # Not after a reload either.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(events) == 1


async def test_bargains_not_polled_while_closed(hass: HomeAssistant, api, amsterdam) -> None:
    entry = await setup_appie(hass)
    assert api["get_bargains"].await_count == 1
    await _tick(hass, amsterdam, LATE)
    await entry.runtime_data.bargains.async_refresh()
    assert api["get_bargains"].await_count == 1
    assert hass.states.get("sensor.albert_heijn_koopjes").state == "2"

    # Open again the next morning: polled on the interval.
    await _tick(hass, amsterdam, "2026-10-28T08:30:00+00:00")
    await _tick(hass, amsterdam, "2026-10-28T09:01:00+00:00")
    assert api["get_bargains"].await_count >= 2


async def test_no_favorite_store(hass: HomeAssistant, api, amsterdam) -> None:
    api["get_favorite_store"].return_value = {"data": {"storesFavouriteStore": None}}
    entry = await setup_appie(hass)
    assert entry.state.name == "LOADED"
    assert hass.states.get("sensor.albert_heijn_winkel").state == "unavailable"
    assert hass.states.get("binary_sensor.albert_heijn_winkel_open").state == "unavailable"
    assert hass.states.get("sensor.albert_heijn_koopjes").state == "0"
    api["get_bargains"].assert_not_awaited()


async def test_store_redacted_in_diagnostics(hass: HomeAssistant, api, amsterdam) -> None:
    entry = await setup_appie(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["store"]["address"] == "**REDACTED**"
    assert diag["store"]["id"] == 1527
    assert "Nachtegaalstraat" not in str(diag)


async def test_open_from_and_until_today(hass: HomeAssistant, api, amsterdam) -> None:
    # 06:00 in Amsterdam: not open yet, but today's hours are known.
    amsterdam.move_to("2026-10-27T05:00:00+00:00")
    await setup_appie(hass)
    assert hass.states.get("binary_sensor.albert_heijn_winkel_open").state == "off"
    assert hass.states.get("sensor.albert_heijn_winkel_open_vanaf").state == "08:00"
    assert hass.states.get("sensor.albert_heijn_winkel_open_tot").state == "22:00"

    # Wednesday closes at midnight.
    await _tick(hass, amsterdam, "2026-10-28T09:00:00+00:00")
    assert hass.states.get("sensor.albert_heijn_winkel_open_tot").state == "00:00"

    # Thursday: closed all day.
    await _tick(hass, amsterdam, "2026-10-29T09:00:00+00:00")
    assert hass.states.get("sensor.albert_heijn_winkel_open_vanaf").state == "gesloten"
    assert hass.states.get("sensor.albert_heijn_winkel_open_tot").state == "gesloten"
