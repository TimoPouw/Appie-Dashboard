"""List cost and "vergeet niet": follow the list, throttled."""

import copy
from datetime import timedelta

from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.appie.api import AppieError

from .common import setup_appie
from .test_models import LIST


def _list_with(**changes) -> dict:
    """LIST with the quantity of product 111 and/or the free text changed."""
    raw = copy.deepcopy(LIST)
    if "butter" in changes:
        raw["items"][0]["quantity"] = changes["butter"]
    if "text" in changes:
        raw["items"].append({"listItemId": 0, "strikedthrough": False, "quantity": 1, "description": changes["text"],
                             "type": "SHOPPABLE", "originCode": "TXT"})
    return raw


async def _list_poll(hass: HomeAssistant, entry, raw: dict) -> None:
    entry.runtime_data.shopping_list.client.get_list.return_value = raw
    await entry.runtime_data.shopping_list.async_refresh()
    await hass.async_block_till_done()


async def test_list_cost_sensor(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    # Only open products, with their quantity; free text and ticked items are left out.
    api["get_total_price"].assert_awaited_once_with([{"id": 111, "quantity": 1}, {"id": 222, "quantity": 2}])
    state = hass.states.get("sensor.albert_heijn_lijst_kosten")
    assert float(state.state) == 5.2
    assert state.attributes["unit_of_measurement"] == "EUR"
    assert state.attributes["device_class"] == "monetary"
    assert state.attributes["zonder_korting"] == 5.58
    assert state.attributes["korting"] == 0.38
    assert state.attributes["aantal_producten"] == 2
    assert state.attributes["aantal_vrije_tekst"] == 1


async def test_list_cost_burst_is_one_call(hass: HomeAssistant, api) -> None:
    entry = await setup_appie(hass)
    assert api["get_total_price"].await_count == 1

    # The first edit is priced right away...
    await _list_poll(hass, entry, _list_with(butter=2))
    assert api["get_total_price"].await_count == 2
    # ...more quick edits wait for the cooldown...
    for quantity in (3, 4):
        await _list_poll(hass, entry, _list_with(butter=quantity))
    assert api["get_total_price"].await_count == 2

    # ...and then cost one call, with the latest list.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert api["get_total_price"].await_count == 3
    assert api["get_total_price"].await_args.args[0][0] == {"id": 111, "quantity": 4}

    # An unchanged list on the next poll costs nothing.
    await _list_poll(hass, entry, _list_with(butter=4))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=200))
    await hass.async_block_till_done()
    assert api["get_total_price"].await_count == 3


async def test_list_cost_free_text_needs_no_call(hass: HomeAssistant, api) -> None:
    entry = await setup_appie(hass)
    await _list_poll(hass, entry, _list_with(text="Kaas"))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert api["get_total_price"].await_count == 1
    assert hass.states.get("sensor.albert_heijn_lijst_kosten").attributes["aantal_vrije_tekst"] == 2


async def test_list_cost_empty_list(hass: HomeAssistant, api) -> None:
    api["get_list"].return_value = {"items": []}
    await setup_appie(hass)
    api["get_total_price"].assert_not_awaited()
    assert float(hass.states.get("sensor.albert_heijn_lijst_kosten").state) == 0


async def test_list_cost_failure_keeps_rest_working(hass: HomeAssistant, api) -> None:
    api["get_total_price"].side_effect = AppieError("boom")
    entry = await setup_appie(hass)
    assert entry.state.name == "LOADED"
    assert hass.states.get("sensor.albert_heijn_lijst_kosten").state == "unavailable"
    assert hass.states.get("sensor.albert_heijn_bonus_voor_ons").state == "4"


async def test_dont_forget_sensor(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    api["get_dont_forget"].assert_awaited_once_with(
        [{"quantity": 1, "position": 1, "productId": 111}, {"quantity": 2, "position": 2, "productId": 222}]
    )
    state = hass.states.get("sensor.albert_heijn_vergeet_niet")
    assert state.state == "2"
    assert state.attributes["suggesties"] == [
        {"product_id": 2600, "title": "AH Goudse jong 48+ plakken", "image": "https://img.invalid/kaas",
         "size": "190 g", "is_bonus": True, "bonus_mechanism": "2e halve prijs", "price": 2.21, "price_before": 2.95},
        {"product_id": 3100, "title": "AH Scharreleieren", "image": None, "size": "10 stuks", "is_bonus": False,
         "bonus_mechanism": None, "price": 3.49, "price_before": None},
    ]


async def test_dont_forget_at_most_every_15_minutes(hass: HomeAssistant, api) -> None:
    entry = await setup_appie(hass)
    assert api["get_dont_forget"].await_count == 1

    # The first change is fetched right away...
    await _list_poll(hass, entry, _list_with(butter=2))
    assert api["get_dont_forget"].await_count == 2
    # ...later changes wait for the 15 minutes to pass, and then count once.
    for quantity in (3, 4, 5):
        await _list_poll(hass, entry, _list_with(butter=quantity))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=10))
    await hass.async_block_till_done()
    assert api["get_dont_forget"].await_count == 2
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=16))
    await hass.async_block_till_done()
    assert api["get_dont_forget"].await_count == 3
    assert api["get_dont_forget"].await_args.args[0][0]["quantity"] == 5


async def test_dont_forget_empty_list_makes_no_call(hass: HomeAssistant, api) -> None:
    api["get_list"].return_value = {"items": []}
    await setup_appie(hass)
    api["get_dont_forget"].assert_not_awaited()
    assert hass.states.get("sensor.albert_heijn_vergeet_niet").state == "0"
