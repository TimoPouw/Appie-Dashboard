"""Product services: one product, several products, sub-categories."""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.appie.api import AppieClient
from custom_components.appie.const import API_BASE, DOMAIN

from .common import TOKENS, setup_appie


async def test_get_product(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    product = await hass.services.async_call(
        DOMAIN, "get_product", {"product_id": 436752}, blocking=True, return_response=True
    )
    api["get_product_detail"].assert_awaited_with(436752)
    api["get_nutrition"].assert_awaited_with(436752)
    assert product == {
        "product_id": 436752, "title": "AH Biologisch Rundergehakt", "size": "300 g", "price": 5.66,
        "image": "https://img.invalid/gehakt", "is_bonus": True, "bonus_mechanism": "10% KORTING",
        "brand": "AH Biologisch", "category": "Vlees", "subcategory": "Rundergehakt", "nutriscore": "D",
        "orderable": True, "previously_bought": True, "properties": ["biologisch"],
        "description": "Biologisch rundergehakt",
        "nutrition": [{"name": "Energie", "value": "1011 kJ (243 kcal)"}, {"name": "Vet", "value": "18 g"}],
    }

    api["get_product_detail"].return_value = {}
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "get_product", {"product_id": 1}, blocking=True, return_response=True)


async def test_get_products(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    api["get_products"].return_value = {
        111: {"webshopId": 111, "title": "AH Roomboter", "salesUnitSize": "250 g", "priceBeforeBonus": 3.29},
        900: {"webshopId": 900, "title": "AH Halfvolle melk 2L", "currentPrice": 2.19},
    }
    response = await hass.services.async_call(
        DOMAIN, "get_products", {"product_ids": [900, 111, 5]}, blocking=True, return_response=True
    )
    api["get_products"].assert_awaited_with([900, 111, 5])
    assert [p["product_id"] for p in response["producten"]] == [900, 111]
    assert response["producten"][1]["price"] == 3.29


async def test_get_subcategories(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    response = await hass.services.async_call(
        DOMAIN, "get_subcategories", {"categorie_id": 6401}, blocking=True, return_response=True
    )
    api["get_subcategories"].assert_awaited_with(6401)
    assert response == {"antwoord": [{"id": 6402, "name": "Gehakt"}]}


async def test_product_endpoints(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API_BASE}/mobile-services/product/detail/v4/fir/436752", json={"productCard": {}})
    aioclient_mock.get(f"{API_BASE}/mobile-services/v1/product-shelves/categories/6401/sub-categories", json=[])
    aioclient_mock.post(f"{API_BASE}/graphql", json={"data": {"product": None}})
    client = AppieClient(async_get_clientsession(hass), TOKENS)
    await client.get_product_detail(436752)
    await client.get_subcategories(6401)
    await client.get_nutrition(436752)
    body = aioclient_mock.mock_calls[2][2]
    assert body["variables"] == {"productId": 436752} and "tradeItem" in body["query"]
