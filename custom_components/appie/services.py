"""Services: product search, adding a product by name, recipes, receipts."""

from __future__ import annotations

from dataclasses import asdict

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api import AppieError
from .const import DOMAIN
from .coordinator import AppieConfigEntry
from .models import (
    best_match,
    new_product_item,
    parse_receipt_detail,
    parse_recipe_search,
    parse_search,
    receipt_view,
)

SERVICE_SEARCH = "search"
SERVICE_ADD_PRODUCT = "add_product"
SERVICE_SEARCH_RECIPES = "search_recipes"
SERVICE_GET_RECEIPT = "get_receipt"

ATTR_QUERY = "zoekterm"
ATTR_COUNT = "aantal"
ATTR_RECEIPT_ID = "receipt_id"

# Enough results for add_product to find a product we often buy.
ADD_PRODUCT_CANDIDATES = 20

SEARCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_QUERY): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_COUNT, default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
    }
)
ADD_PRODUCT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_QUERY): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_COUNT, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
    }
)
RECIPES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_QUERY): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_COUNT, default=7): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
    }
)
RECEIPT_SCHEMA = vol.Schema({vol.Optional(ATTR_RECEIPT_ID): cv.string})


def _entry(hass: HomeAssistant) -> AppieConfigEntry:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="not_loaded"
    )


async def _search(hass: HomeAssistant, query: str, size: int):
    try:
        raw = await _entry(hass).runtime_data.client.search_products(query.strip(), size)
    except AppieError as err:
        raise HomeAssistantError(f"Albert Heijn: {err}") from err
    return parse_search(raw)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services (once, for all entries)."""

    async def search(call: ServiceCall) -> ServiceResponse:
        results = await _search(hass, call.data[ATTR_QUERY], call.data[ATTR_COUNT])
        return {"producten": [r.as_dict() for r in results[: call.data[ATTR_COUNT]]]}

    async def add_product(call: ServiceCall) -> ServiceResponse:
        query = call.data[ATTR_QUERY]
        data = _entry(hass).runtime_data
        results = await _search(hass, query, ADD_PRODUCT_CANDIDATES)
        match = best_match(results, data.favorites.data or [])
        if match is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_product",
                translation_placeholders={"query": query},
            )
        product, reason = match
        wanted = new_product_item(product.product_id, product.title)
        current = next((i for i in data.shopping_list.data or [] if i.key == wanted.key), None)
        count = call.data[ATTR_COUNT]
        if current is None:
            quantity, body = count, wanted.patch(quantity=count)
        elif current.checked:
            # Ticked off earlier: put it back as a fresh item.
            quantity, body = count, current.patch(quantity=count, checked=False)
        else:
            quantity = current.quantity + count
            body = current.patch(quantity=quantity)
        try:
            await data.client.patch_list([body])
        except AppieError as err:
            raise HomeAssistantError(f"Albert Heijn: {err}") from err
        await data.shopping_list.async_refresh()
        return {**product.as_dict(), "match": reason, "quantity_on_list": quantity}

    async def search_recipes(call: ServiceCall) -> ServiceResponse:
        client = _entry(hass).runtime_data.client
        try:
            raw = await client.search_recipes(call.data[ATTR_QUERY].strip(), call.data[ATTR_COUNT])
        except AppieError as err:
            raise HomeAssistantError(f"Albert Heijn: {err}") from err
        recipes, total = parse_recipe_search(raw)
        return {"recepten": [asdict(r) for r in recipes[: call.data[ATTR_COUNT]]], "totaal": total}

    async def get_receipt(call: ServiceCall) -> ServiceResponse:
        data = _entry(hass).runtime_data
        receipts = data.receipts.data
        receipt_id = call.data.get(ATTR_RECEIPT_ID) or (receipts.latest.id if receipts and receipts.latest else None)
        # Only the account's own recent receipts.
        receipt = data.receipt_viewer.find(receipt_id) if receipt_id else None
        if receipt is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_receipt",
                translation_placeholders={"receipt_id": str(receipt_id)},
            )
        if receipts.latest_detail and receipts.latest_detail.id == receipt.id:
            detail = receipts.latest_detail
        else:
            try:
                detail = parse_receipt_detail(await data.client.get_receipt_detail(receipt.id))
            except AppieError as err:
                raise HomeAssistantError(f"Albert Heijn: {err}") from err
        view = receipt_view(receipt, detail, dt_util.get_default_time_zone())
        return {**view, "pdf_url": data.receipt_viewer.pdf_url(receipt.id)}

    hass.services.async_register(
        DOMAIN, SERVICE_GET_RECEIPT, get_receipt, schema=RECEIPT_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEARCH_RECIPES, search_recipes, schema=RECIPES_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEARCH, search, schema=SEARCH_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_PRODUCT, add_product, schema=ADD_PRODUCT_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
