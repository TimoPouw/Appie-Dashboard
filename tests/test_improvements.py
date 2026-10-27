"""Options, the "vaak gekocht" sensor, live bonus matching, search services and redaction."""

import logging

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.appie.api import AppieClient, redact
from custom_components.appie.const import API_BASE, DOMAIN
from custom_components.appie.diagnostics import async_get_config_entry_diagnostics

from .common import SEARCH, TOKENS, setup_appie
from .test_models import LIST


async def test_options_change_button_count(hass: HomeAssistant, api) -> None:
    entry = await setup_appie(hass)
    registry = er.async_get(hass)
    assert registry.async_get("button.albert_heijn_vaak_gekocht_10")
    assert registry.async_get("button.albert_heijn_vaak_gekocht_11") is None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"favorites_count": 12, "favorites_days": 60}
    )
    await hass.async_block_till_done()
    assert entry.options == {"favorites_count": 12, "favorites_days": 60}
    # Reloaded without a restart: the new coordinator uses the new options.
    assert entry.runtime_data.favorites.count == 12
    assert entry.runtime_data.favorites.days == 60
    assert registry.async_get("button.albert_heijn_vaak_gekocht_12")

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"favorites_count": 10, "favorites_days": 60}
    )
    await hass.async_block_till_done()
    assert registry.async_get("button.albert_heijn_vaak_gekocht_10")
    assert registry.async_get("button.albert_heijn_vaak_gekocht_11") is None
    assert registry.async_get("button.albert_heijn_vaak_gekocht_12") is None
    assert hass.states.get("button.albert_heijn_vaak_gekocht_12") is None


async def test_options_reject_out_of_range(hass: HomeAssistant, api) -> None:
    entry = await setup_appie(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(Exception):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"favorites_count": 51, "favorites_days": 60}
        )


async def test_token_refresh_does_not_reload(hass: HomeAssistant, api) -> None:
    entry = await setup_appie(hass)
    data = entry.runtime_data
    hass.config_entries.async_update_entry(entry, data={**entry.data, "access_token": "12345_new"})
    await hass.async_block_till_done()
    assert entry.runtime_data is data


async def test_favorites_sensor(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    state = hass.states.get("sensor.albert_heijn_vaak_gekocht")
    assert state.state == "2"
    products = state.attributes["producten"]
    assert [p["rank"] for p in products] == [1, 2]
    butter = next(p for p in products if p["title"] == "AH Roomboter")
    assert butter == {
        "rank": butter["rank"], "title": "AH Roomboter", "times_bought": 3, "product_id": 111, "bonus": None,
        "on_list": True, "quantity_on_list": 1, "entity_picture": None,
    }
    # Same fields as the matching button.
    button = hass.states.get(f"button.albert_heijn_vaak_gekocht_{butter['rank']}")
    for key in ("rank", "title", "times_bought", "product_id", "bonus", "on_list", "quantity_on_list"):
        assert button.attributes[key] == butter[key]


async def test_bonus_follows_list_without_api_call(hass: HomeAssistant, api) -> None:
    # A bonus week that has not ended yet, so the list change needs no new fetch.
    api["get_bonus_metadata"].return_value = {
        "periods": [{"bonusStartDate": "2099-01-05", "bonusEndDate": "2099-01-11"}]
    }
    entry = await setup_appie(hass)
    bonus = entry.runtime_data.bonus
    state = hass.states.get("sensor.albert_heijn_bonus_voor_ons")
    assert state.attributes["on_list"] == 1
    calls = api["get_personal_bonus"].await_count
    timer = bonus._unsub_refresh

    # The courgette leaves the list.
    api["get_list"].return_value = {"items": [i for i in LIST["items"] if i.get("productDetails", {})
                                              .get("product", {}).get("webshopId") != 222]}
    await entry.runtime_data.shopping_list.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.albert_heijn_bonus_voor_ons")
    assert state.attributes["on_list"] == 0
    assert all(not o["on_list"] for o in state.attributes["offers"])
    assert api["get_personal_bonus"].await_count == calls
    # The 6 h bonus timer keeps running instead of restarting every minute.
    assert bonus._unsub_refresh is timer


async def test_search_service(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    response = await hass.services.async_call(
        DOMAIN, "search", {"zoekterm": "melk", "aantal": 2}, blocking=True, return_response=True
    )
    api["search_products"].assert_awaited_with("melk", 2)
    assert response["producten"] == [
        {"product_id": 900, "title": "AH Halfvolle melk 2L", "size": "2 l", "price": 2.19, "image": None,
         "is_bonus": False, "bonus_mechanism": None},
        {"product_id": 111, "title": "AH Roomboter", "size": "250 g", "price": 2.89,
         "image": "https://img.invalid/200", "is_bonus": True, "bonus_mechanism": "2e halve prijs"},
    ]


async def test_add_product_prefers_favorites(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    await hass.async_block_till_done()

    # AH Roomboter is in "vaak gekocht" and already on the list once.
    response = await hass.services.async_call(
        DOMAIN, "add_product", {"zoekterm": "boter"}, blocking=True, return_response=True
    )
    assert response["product_id"] == 111 and response["match"] == "vaak_gekocht"
    assert response["quantity_on_list"] == 2
    body = api["patch_list"].await_args.args[0]
    assert body == [{"description": "AH Roomboter", "searchTerm": "AH Roomboter", "type": "SHOPPABLE",
                     "originCode": "PRD", "quantity": 2, "strikeThrough": False, "productId": 111}]

    # No favorite among the results: something bought before wins.
    api["search_products"].return_value = {"products": [SEARCH["products"][0], SEARCH["products"][2]]}
    response = await hass.services.async_call(
        DOMAIN, "add_product", {"zoekterm": "halfvolle melk"}, blocking=True, return_response=True
    )
    assert response["product_id"] == 901 and response["match"] == "eerder_gekocht"
    body = api["patch_list"].await_args.args[0][0]
    assert body["productId"] == 901 and body["quantity"] == 1 and body["originCode"] == "PRD"

    # Otherwise the most relevant result.
    api["search_products"].return_value = {"products": [SEARCH["products"][0]]}
    response = await hass.services.async_call(
        DOMAIN, "add_product", {"zoekterm": "halfvolle melk", "aantal": 3}, blocking=True, return_response=True
    )
    assert response["match"] == "beste_zoekresultaat" and response["quantity_on_list"] == 3

    api["search_products"].return_value = {"products": []}
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "add_product", {"zoekterm": "xyzzy"}, blocking=True, return_response=True
        )


async def test_services_need_a_loaded_entry(hass: HomeAssistant, api) -> None:
    entry = await setup_appie(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "search", {"zoekterm": "melk"}, blocking=True, return_response=True)


def test_redact_keeps_products_and_drops_personal_data() -> None:
    raw = {
        "access_token": "secret", "refresh_token": "secret2",
        "member": {"name": {"first": "Jan"}, "emailAddress": "jan@example.com",
                   "address": {"street": "Hoofdstraat"}},
        "products": [{"name": "BIO BANAAN", "title": "Bio banaan"}],
    }
    clean = redact(raw)
    assert clean["access_token"] == clean["refresh_token"] == "**REDACTED**"
    assert clean["member"] == {"name": "**REDACTED**", "emailAddress": "**REDACTED**", "address": "**REDACTED**"}
    assert clean["products"] == [{"name": "BIO BANAAN", "title": "Bio banaan"}]


async def test_debug_log_is_redacted(hass: HomeAssistant, aioclient_mock, caplog) -> None:
    aioclient_mock.get(
        f"{API_BASE}/mobile-services/product/search/v2",
        json={"products": [], "access_token": "leaked-token", "address": {"street": "Hoofdstraat"}},
    )
    client = AppieClient(async_get_clientsession(hass), TOKENS)
    with caplog.at_level(logging.DEBUG, logger="custom_components.appie.api"):
        await client.search_products("melk", 5)
    url = aioclient_mock.mock_calls[0][1]
    assert url.path == "/mobile-services/product/search/v2"
    assert dict(url.query) == {"query": "melk", "page": "0", "size": "5", "sortOn": "RELEVANCE"}
    assert "/mobile-services/product/search/v2" in caplog.text
    assert "leaked-token" not in caplog.text and "Hoofdstraat" not in caplog.text
    assert "12345_abc" not in caplog.text


async def test_diagnostics_redacts(hass: HomeAssistant, api) -> None:
    entry = await setup_appie(hass, options={"favorites_count": 10, "favorites_days": 90})
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["access_token"] == "**REDACTED**"
    assert diag["entry"]["refresh_token"] == "**REDACTED**"
    assert diag["options"] == {"favorites_count": 10, "favorites_days": 90}
