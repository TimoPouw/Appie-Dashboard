"""Services: product search and adding a product to the list by name."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import AppieError
from .const import DOMAIN
from .coordinator import AppieConfigEntry
from .models import best_match, new_product_item, parse_search

SERVICE_SEARCH = "search"
SERVICE_ADD_PRODUCT = "add_product"

ATTR_QUERY = "zoekterm"
ATTR_COUNT = "aantal"

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

    hass.services.async_register(
        DOMAIN, SERVICE_SEARCH, search, schema=SEARCH_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_PRODUCT, add_product, schema=ADD_PRODUCT_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
