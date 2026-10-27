"""Spotlight bonus, bonus per category and the Bonus Box."""

from datetime import date

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.appie.api import AppieClient, AppieError
from custom_components.appie.const import API_BASE, DOMAIN

from .common import BONUS_BOX, TOKENS, setup_appie


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
        "price": 2.0, "price_was": 2.99, "image": None, "hq_id": 894018, "activated": True,
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


PROBE_ERROR = {"errors": [{"message": "Validation error (MissingFieldArgument@[bonusActivatePersonalPromotion]) : "
                                      "Field 'bonusActivatePersonalPromotion' argument 'id' of type 'String!' is "
                                      "required, but it was not provided."}]}


def test_required_arguments_and_values() -> None:
    from custom_components.appie.models import activation_values, required_arguments

    args = required_arguments([PROBE_ERROR["errors"][0]["message"]])
    assert args == [("id", "String!")]
    offer = {"id": "385569", "hq_id": 894019, "start_date": "2026-02-09", "end_date": "2026-02-15"}
    assert activation_values(args, offer) == {"id": "385569"}
    assert activation_values([("hqId", "Int!"), ("periodStart", "String")], offer) == {
        "hqId": 894019, "periodStart": "2026-02-09"}
    # An argument we can't place: nothing is sent.
    assert activation_values([("memberId", "Int!")], offer) is None


async def test_activation_probes_then_activates(hass: HomeAssistant, aioclient_mock) -> None:
    calls = []

    async def graphql(method, url, data):
        calls.append(data)
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        body = PROBE_ERROR if len(calls) == 1 else {
            "data": {"bonusActivatePersonalPromotion": {"status": "SUCCESS", "message": None}}}
        return AiohttpClientMockResponse(method, url, json=body)

    aioclient_mock.post(f"{API_BASE}/graphql", side_effect=graphql)
    client = AppieClient(async_get_clientsession(hass), TOKENS)
    result = await client.activate_bonus_offer({"id": "385569", "hq_id": 894019})
    assert result == {"status": "SUCCESS", "message": None}
    # First the probe without arguments, then the real call with the discovered one.
    assert "bonusActivatePersonalPromotion {" in calls[0]["query"] and calls[0]["variables"] == {}
    assert "($id: String!)" in calls[1]["query"] and calls[1]["variables"] == {"id": "385569"}


async def test_activation_refuses_unknown_arguments(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(f"{API_BASE}/graphql", json={"errors": [{"message":
        "Field 'bonusActivatePersonalPromotion' argument 'memberId' of type 'Int!' is required"}]})
    client = AppieClient(async_get_clientsession(hass), TOKENS)
    with pytest.raises(AppieError, match="memberId"):
        await client.activate_bonus_offer({"id": "1"})
    assert len(aioclient_mock.mock_calls) == 1


async def test_activate_bonus_service(hass: HomeAssistant, api) -> None:
    from unittest.mock import AsyncMock, patch

    entry = await setup_appie(hass)
    activated = {"data": {**BONUS_BOX["data"], "bonusPromotions": [
        BONUS_BOX["data"]["bonusPromotions"][0],
        {**BONUS_BOX["data"]["bonusPromotions"][1], "activationStatus": "ACTIVATED"}]}}
    with patch("custom_components.appie.api.AppieClient.activate_bonus_offer",
               AsyncMock(return_value={"status": "SUCCESS", "message": None})) as activate:
        api["get_bonus_box"].return_value = activated
        response = await hass.services.async_call(
            DOMAIN, "activate_bonus", {"aanbieding": "ah hummus"}, blocking=True, return_response=True)
    assert activate.await_args.args[0]["id"] == "385569"
    assert response == {"id": "385569", "title": "AH Hummus", "geactiveerd": True, "status": "SUCCESS",
                        "message": None}
    assert entry.runtime_data.bonus_box.data.activated == 2

    # Already activated: no call.
    response = await hass.services.async_call(
        DOMAIN, "activate_bonus", {"aanbieding": "385568"}, blocking=True, return_response=True)
    assert response["status"] == "al_geactiveerd"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "activate_bonus", {"aanbieding": "bestaat niet"},
                                       blocking=True, return_response=True)
