"""Services: products, bonus, favorite lists, adding by name, receipts."""

from __future__ import annotations

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
    SOURCE_CATEGORY,
    bonus_categories,
    parse_bonus_section,
    parse_favorite_list_items,
    best_match,
    find_favorite_list,
    new_product_item,
    parse_product_detail,
    parse_receipt_detail,
    parse_search,
    receipt_view,
)

SERVICE_SEARCH = "search"
SERVICE_ADD_PRODUCT = "add_product"
SERVICE_GET_RECEIPT = "get_receipt"
SERVICE_GET_PRODUCT = "get_product"
SERVICE_GET_PRODUCTS = "get_products"
SERVICE_GET_SUBCATEGORIES = "get_subcategories"
SERVICE_BONUS = "bonus"
SERVICE_GET_FAVORITE_LIST = "get_favorite_list"
SERVICE_ADD_TO_FAVORITE_LIST = "add_to_favorite_list"
SERVICE_FAVORITE_LIST_TO_LIST = "favorite_list_to_list"

ATTR_QUERY = "zoekterm"
ATTR_COUNT = "aantal"
ATTR_RECEIPT_ID = "receipt_id"
ATTR_PRODUCT_ID = "product_id"
ATTR_PRODUCT_IDS = "product_ids"
ATTR_CATEGORY_ID = "categorie_id"
ATTR_CATEGORY = "categorie"
ATTR_LIST = "lijst"

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
PRODUCT_SCHEMA = vol.Schema({vol.Required(ATTR_PRODUCT_ID): vol.All(vol.Coerce(int), vol.Range(min=1))})
PRODUCTS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PRODUCT_IDS): vol.All(
            cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=1))], vol.Length(min=1, max=50)
        )
    }
)
SUBCATEGORIES_SCHEMA = vol.Schema({vol.Required(ATTR_CATEGORY_ID): vol.All(vol.Coerce(int), vol.Range(min=1))})
FAVORITE_LIST_SCHEMA = vol.Schema({vol.Required(ATTR_LIST): vol.All(cv.string, vol.Length(min=1))})
ADD_TO_FAVORITE_LIST_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(ATTR_LIST): vol.All(cv.string, vol.Length(min=1)),
            vol.Optional(ATTR_QUERY): vol.All(cv.string, vol.Length(min=1)),
            vol.Optional(ATTR_PRODUCT_ID): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Optional(ATTR_COUNT, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
        }
    ),
    cv.has_at_least_one_key(ATTR_QUERY, ATTR_PRODUCT_ID),
)
BONUS_SCHEMA = vol.Schema({vol.Optional(ATTR_CATEGORY): cv.string})
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

    async def get_product(call: ServiceCall) -> ServiceResponse:
        client = _entry(hass).runtime_data.client
        product_id = call.data[ATTR_PRODUCT_ID]
        try:
            detail = await client.get_product_detail(product_id)
            nutrition = await client.get_nutrition(product_id)
        except AppieError as err:
            raise HomeAssistantError(f"Albert Heijn: {err}") from err
        product = parse_product_detail(detail or {}, nutrition)
        if product is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_product",
                translation_placeholders={"product_id": str(product_id)},
            )
        return product

    async def get_products(call: ServiceCall) -> ServiceResponse:
        ids = call.data[ATTR_PRODUCT_IDS]
        try:
            products = await _entry(hass).runtime_data.client.get_products(ids)
        except AppieError as err:
            raise HomeAssistantError(f"Albert Heijn: {err}") from err
        # In the order asked; products AH doesn't sell online are left out.
        return {"producten": [r.as_dict() for r in parse_search([products[i] for i in ids if i in products])]}

    async def get_subcategories(call: ServiceCall) -> ServiceResponse:
        try:
            raw = await _entry(hass).runtime_data.client.get_subcategories(call.data[ATTR_CATEGORY_ID])
        except AppieError as err:
            raise HomeAssistantError(f"Albert Heijn: {err}") from err
        return {"antwoord": raw}

    async def _favorite_list(name: str):
        coordinator = _entry(hass).runtime_data.favorite_lists
        found = find_favorite_list(coordinator.data or [], name)
        if found is None:
            # Maybe made in the app since the last poll.
            await coordinator.async_refresh()
            if not coordinator.last_update_success:
                raise HomeAssistantError(f"Albert Heijn: {coordinator.last_exception}")
            found = find_favorite_list(coordinator.data or [], name)
        lists = coordinator.data or []
        if found is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_list",
                translation_placeholders={"list": name, "lists": ", ".join(fl.naam for fl in lists)},
            )
        return found

    async def _list_products(list_id: str) -> list[tuple[int, int, dict | None]]:
        """(product id, quantity, product card or None) for each product on a favorite list."""
        client = _entry(hass).runtime_data.client
        try:
            items = parse_favorite_list_items(await client.get_favorite_list_items(list_id))
            cards = await client.get_products([pid for pid, _ in items])
        except AppieError as err:
            raise HomeAssistantError(f"Albert Heijn: {err}") from err
        return [(pid, quantity, cards.get(pid)) for pid, quantity in items]

    async def get_favorite_list(call: ServiceCall) -> ServiceResponse:
        found = await _favorite_list(call.data[ATTR_LIST])
        products = []
        for pid, quantity, card in await _list_products(found.id):
            product = parse_search([card])[0].as_dict() if card else {"product_id": pid, "title": None}
            products.append({**product, "quantity": quantity})
        return {"lijst": found.naam, "id": found.id, "producten": products}

    async def add_to_favorite_list(call: ServiceCall) -> ServiceResponse:
        data = _entry(hass).runtime_data
        found = await _favorite_list(call.data[ATTR_LIST])
        if ATTR_PRODUCT_ID in call.data:
            product_id, chosen = call.data[ATTR_PRODUCT_ID], {"product_id": call.data[ATTR_PRODUCT_ID]}
        else:
            match = best_match(
                await _search(hass, call.data[ATTR_QUERY], ADD_PRODUCT_CANDIDATES), data.favorites.data or []
            )
            if match is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="no_product",
                    translation_placeholders={"query": call.data[ATTR_QUERY]},
                )
            product_id, chosen = match[0].product_id, {**match[0].as_dict(), "match": match[1]}
        try:
            await data.client.add_to_favorite_list(
                found.id, [{"productId": product_id, "quantity": call.data[ATTR_COUNT]}]
            )
        except AppieError as err:
            raise HomeAssistantError(f"Albert Heijn: {err}") from err
        await data.favorite_lists.async_refresh()
        return {**chosen, "lijst": found.naam, "quantity": call.data[ATTR_COUNT]}

    async def favorite_list_to_list(call: ServiceCall) -> ServiceResponse:
        data = _entry(hass).runtime_data
        found = await _favorite_list(call.data[ATTR_LIST])
        current = {i.product_id: i for i in data.shopping_list.data or [] if i.product_id}
        body, added, already = [], [], []
        for pid, quantity, card in await _list_products(found.id):
            title = (card or {}).get("title") or str(pid)
            item = current.get(pid)
            if item and not item.checked and item.quantity >= quantity:
                already.append({"product_id": pid, "title": title})
                continue
            if item:
                # Ticked off, or fewer than the favorite list has: bring it up, never lower.
                body.append(item.patch(quantity=quantity, checked=False))
            else:
                body.append(new_product_item(pid, title).patch(quantity=quantity))
            added.append({"product_id": pid, "title": title, "quantity": quantity})
        if body:
            try:
                await data.client.patch_list(body)
            except AppieError as err:
                raise HomeAssistantError(f"Albert Heijn: {err}") from err
            await data.shopping_list.async_refresh()
        return {"lijst": found.naam, "toegevoegd": added, "al_op_lijst": already}

    async def bonus(call: ServiceCall) -> ServiceResponse:
        client = _entry(hass).runtime_data.client
        today = dt_util.now().date()
        try:
            categories = bonus_categories(await client.get_bonus_metadata() or {})
            category = call.data.get(ATTR_CATEGORY)
            if not category:
                return {"categorieen": categories}
            match = next((c for c in categories if c.lower() == category.strip().lower()), None)
            if match is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_category",
                    translation_placeholders={"category": category, "categories": ", ".join(categories)},
                )
            raw = await client.get_bonus_category(match, today)
        except AppieError as err:
            raise HomeAssistantError(f"Albert Heijn: {err}") from err
        offers = parse_bonus_section(raw or {}, SOURCE_CATEGORY)
        return {"categorie": match, "aanbiedingen": [o.as_dict() for o in offers]}

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
        DOMAIN, SERVICE_GET_PRODUCT, get_product, schema=PRODUCT_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_PRODUCTS, get_products, schema=PRODUCTS_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SUBCATEGORIES,
        get_subcategories,
        schema=SUBCATEGORIES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_FAVORITE_LIST,
        get_favorite_list,
        schema=FAVORITE_LIST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_TO_FAVORITE_LIST,
        add_to_favorite_list,
        schema=ADD_TO_FAVORITE_LIST_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FAVORITE_LIST_TO_LIST,
        favorite_list_to_list,
        schema=FAVORITE_LIST_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_BONUS, bonus, schema=BONUS_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_RECEIPT, get_receipt, schema=RECEIPT_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEARCH, search, schema=SEARCH_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_PRODUCT, add_product, schema=ADD_PRODUCT_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
