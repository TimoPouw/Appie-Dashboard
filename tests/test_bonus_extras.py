"""Spotlight bonus, bonus per category and the Bonus Box."""

from datetime import date

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.appie.api import AppieClient, AppieError
from custom_components.appie.const import API_BASE, DOMAIN

from .common import TOKENS, setup_appie


async def test_spotlight_sensor(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    state = hass.states.get("sensor.albert_heijn_bonus_spotlight")
    assert state.state == "2"
    butter, chips = state.attributes["offers"]
    assert butter["title"] == "AH Roomboter" and butter["mechanism"] == "2e halve prijs"
    assert butter["source"] == "spotlight"
    # The butter is on the shopping list, the chips are not.
    assert butter["on_list"] is True and chips["on_list"] is False
    assert chips["key"] == "group:700"


async def test_bonus_box_sensor(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    # Uses the bonus week from the metadata the bonus coordinator already fetched.
    api["get_bonus_box"].assert_awaited_once_with("2026-10-05", "2026-10-11")
    state = hass.states.get("sensor.albert_heijn_bonus_box")
    assert state.state == "2"
    assert state.attributes["max_activaties"] == 10
    assert state.attributes["geactiveerd"] == 1
    assert state.attributes["aanbiedingen"][0] == {
        "id": "385568", "title": "AH Pancakes", "category": "Maaltijden, salades", "mechanism": "VOOR 2.00",
        "price": 2.0, "price_was": 2.99, "image": None, "activated": True,
        "start_date": "2026-02-09", "end_date": "2026-02-15",
    }
    assert state.attributes["aanbiedingen"][1]["mechanism"] is None


async def test_bonus_box_rejected_keeps_rest(hass: HomeAssistant, api) -> None:
    api["get_bonus_box"].side_effect = AppieError("graphql: Cannot query field")
    entry = await setup_appie(hass)
    assert entry.state.name == "LOADED"
    assert hass.states.get("sensor.albert_heijn_bonus_box").state == "unavailable"
    assert hass.states.get("sensor.albert_heijn_bonus_voor_ons").state == "4"


async def test_bonus_service(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    response = await hass.services.async_call(DOMAIN, "bonus", {}, blocking=True, return_response=True)
    assert response == {"categorieen": ["Groente, aardappelen", "Zuivel, eieren"]}

    response = await hass.services.async_call(
        DOMAIN, "bonus", {"categorie": "zuivel, eieren"}, blocking=True, return_response=True
    )
    assert api["get_bonus_category"].await_args.args[0] == "Zuivel, eieren"
    assert response["categorie"] == "Zuivel, eieren"
    assert response["aanbiedingen"][0]["title"] == "AH Roomboter"
    assert response["aanbiedingen"][0]["source"] == "categorie"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "bonus", {"categorie": "Snoep"}, blocking=True, return_response=True)


async def test_bonus_endpoints(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API_BASE}/mobile-services/bonuspage/v2/section/spotlight", json={})
    aioclient_mock.get(f"{API_BASE}/mobile-services/bonuspage/v2/section", json={})
    aioclient_mock.post(f"{API_BASE}/graphql", json={"data": {}})
    client = AppieClient(async_get_clientsession(hass), TOKENS)
    await client.get_spotlight_bonus(date(2026, 10, 27))
    await client.get_bonus_category("Zuivel, eieren", date(2026, 10, 27))
    await client.get_bonus_box("2026-10-26", "2026-11-01")
    spotlight, section, box = aioclient_mock.mock_calls
    assert dict(spotlight[1].query) == {"application": "AHWEBSHOP", "date": "2026-10-27"}
    assert dict(section[1].query) == {
        "application": "AHWEBSHOP", "date": "2026-10-27", "promotionType": "NATIONAL", "category": "Zuivel, eieren"}
    assert box[2]["variables"]["filterSet"] == "APP_BONUS_BOX"
    assert box[2]["variables"]["states"] == ["ACTIVATABLE", "ACTIVATED"]
    assert "bonusPersonalPromotionBundles" in box[2]["query"]
