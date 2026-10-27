"""Favorite lists ("lijstjes"): sensor and services."""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.appie.api import AppieClient, AppieError
from custom_components.appie.const import API_BASE, DOMAIN

from .common import TOKENS, setup_appie

WEEK = "305e6a50-a970-457b-8831-409f572832d4"
CARDS = {
    111: {"webshopId": 111, "title": "AH Roomboter", "salesUnitSize": "250 g", "priceBeforeBonus": 3.29},
    222: {"webshopId": 222, "title": "AH Courgette", "currentPrice": 0.99},
    555: {"webshopId": 555, "title": "AH Volkoren pasta", "currentPrice": 1.49},
}


async def test_favorite_lists_sensor(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    state = hass.states.get("sensor.albert_heijn_favoriete_lijsten")
    assert state.state == "2"
    assert state.attributes["lijsten"] == [
        {"id": WEEK, "naam": "Weekboodschappen", "aantal": 3, "image": "https://img.invalid/lijst"},
        {"id": "aaaa0000-0000-0000-0000-000000000001", "naam": "Feestje", "aantal": 0, "image": None},
    ]


async def test_get_favorite_list(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    api["get_products"].return_value = {111: CARDS[111], 222: CARDS[222]}
    response = await hass.services.async_call(
        DOMAIN, "get_favorite_list", {"lijst": "weekboodschappen"}, blocking=True, return_response=True
    )
    api["get_favorite_list_items"].assert_awaited_with(WEEK)
    assert response["lijst"] == "Weekboodschappen" and response["id"] == WEEK
    assert [(p["product_id"], p["title"], p["quantity"]) for p in response["producten"]] == [
        (111, "AH Roomboter", 1), (222, "AH Courgette", 3), (555, None, 1)]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "get_favorite_list", {"lijst": "Bestaat niet"}, blocking=True, return_response=True
        )


async def test_add_to_favorite_list(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    await hass.async_block_till_done()
    response = await hass.services.async_call(
        DOMAIN, "add_to_favorite_list", {"lijst": "Feestje", "zoekterm": "boter", "aantal": 2},
        blocking=True, return_response=True,
    )
    api["add_to_favorite_list"].assert_awaited_with(
        "aaaa0000-0000-0000-0000-000000000001", [{"productId": 111, "quantity": 2}]
    )
    assert response["product_id"] == 111 and response["match"] == "vaak_gekocht"
    assert response["lijst"] == "Feestje" and response["quantity"] == 2

    await hass.services.async_call(
        DOMAIN, "add_to_favorite_list", {"lijst": WEEK, "product_id": 441199}, blocking=True, return_response=True
    )
    api["add_to_favorite_list"].assert_awaited_with(WEEK, [{"productId": 441199, "quantity": 1}])

    with pytest.raises(Exception):
        await hass.services.async_call(DOMAIN, "add_to_favorite_list", {"lijst": WEEK}, blocking=True)


async def test_favorite_list_to_list(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    api["get_products"].return_value = CARDS
    response = await hass.services.async_call(
        DOMAIN, "favorite_list_to_list", {"lijst": "Weekboodschappen"}, blocking=True, return_response=True
    )
    # Butter is already on the list once; the courgette (2) is topped up to 3; the pasta is new.
    assert response == {
        "lijst": "Weekboodschappen",
        "toegevoegd": [
            {"product_id": 222, "title": "AH Courgette", "quantity": 3},
            {"product_id": 555, "title": "AH Volkoren pasta", "quantity": 1},
        ],
        "al_op_lijst": [{"product_id": 111, "title": "AH Roomboter"}],
    }
    body = api["patch_list"].await_args.args[0]
    assert [(b["productId"], b["quantity"], b["strikeThrough"]) for b in body] == [(222, 3, False), (555, 1, False)]
    assert all(b["originCode"] == "PRD" for b in body)


async def test_unknown_list_refreshes_once(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    calls = api["get_favorite_lists"].await_count
    api["get_favorite_lists"].return_value = {"data": {"favoriteListV2": [
        {"id": "nieuw-1", "description": "Nieuw", "totalSize": 0}]}}
    api["get_favorite_list_items"].return_value = {"data": {"favoriteListV2": []}}
    response = await hass.services.async_call(
        DOMAIN, "get_favorite_list", {"lijst": "Nieuw"}, blocking=True, return_response=True
    )
    assert api["get_favorite_lists"].await_count == calls + 1
    assert response["producten"] == []

    api["get_favorite_lists"].side_effect = AppieError("down")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "get_favorite_list", {"lijst": "Nog nieuwer"}, blocking=True, return_response=True
        )


async def test_favorite_list_endpoints(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(
        f"{API_BASE}/graphql",
        json={"data": {"favoriteListV2": [], "favoriteListProductsAddV2": {"status": "SUCCESS", "errorMessage": None}}},
    )
    client = AppieClient(async_get_clientsession(hass), TOKENS)
    await client.get_favorite_lists()
    await client.add_to_favorite_list(WEEK, [{"productId": 482500, "quantity": 1}])
    lists, mutation = aioclient_mock.mock_calls
    assert lists[2]["variables"] == {"ids": [], "productIds": []}
    assert "FetchFavoriteLists" in lists[2]["query"]
    assert mutation[2]["variables"] == {
        "favoriteListId": WEEK.upper(), "products": [{"productId": 482500, "quantity": 1}]}
    assert "favoriteListProductsAddV2" in mutation[2]["query"]


async def test_favorite_list_mutation_failure(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(
        f"{API_BASE}/graphql", json={"data": {"favoriteListProductsAddV2": {"status": "FAILED", "errorMessage": "nee"}}}
    )
    client = AppieClient(async_get_clientsession(hass), TOKENS)
    with pytest.raises(AppieError, match="nee"):
        await client.add_to_favorite_list(WEEK, [{"productId": 1, "quantity": 1}])
