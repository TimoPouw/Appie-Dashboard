"""Shared test data and helpers."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.appie.const import DOMAIN

TOKENS = {"access_token": "12345_abc", "refresh_token": "r1", "expires_at": 4_000_000_000}
META = {"periods": [{"bonusStartDate": "2026-10-05", "bonusEndDate": "2026-10-11"}]}

# GET /mobile-services/product/search/v2, shaped like appie-go doc/albertheijn_api.md.
SEARCH = {
    "products": [
        {"webshopId": 900, "title": "AH Halfvolle melk 2L", "salesUnitSize": "2 l", "currentPrice": 2.19,
         "isBonus": False, "isPreviouslyBought": False, "images": []},
        {"webshopId": 111, "title": "AH Roomboter", "salesUnitSize": "250 g", "currentPrice": 2.89,
         "priceBeforeBonus": 3.29, "isBonus": True, "bonusMechanism": "2e halve prijs",
         "isPreviouslyBought": True, "images": [{"width": 200, "height": 200, "url": "https://img.invalid/200"}]},
        {"webshopId": 901, "title": "Campina Halfvolle melk", "salesUnitSize": "1 l", "priceBeforeBonus": 1.59,
         "isBonus": False, "isPreviouslyBought": True},
    ],
    "page": {"number": 0, "size": 3, "totalElements": 3, "totalPages": 1},
}

# GraphQL FetchTotalPrice, the response from appie-go's API doc.
TOTAL_PRICE = {"data": {"totalPrice": {"withoutDiscount": {"amount": 5.58}, "discount": {"amount": 0.38}}}}

# POST /mobile-services/v2/recommendations/dontforgetlane, from appie-go's API doc.
DONT_FORGET = {
    "dataLakeModel": {"name": "TransformerModelWithCategory", "requestId": "", "version": "2026_02_01-11_50"},
    "productCards": [
        {"webshopId": 2600, "title": "AH Goudse jong 48+ plakken", "brand": "AH", "salesUnitSize": "190 g",
         "images": [{"width": 200, "height": 200, "url": "https://img.invalid/kaas"}], "isBonus": True,
         "bonusMechanism": "2e halve prijs", "priceBeforeBonus": 2.95, "currentPrice": 2.21},
        {"webshopId": 3100, "title": "AH Scharreleieren", "salesUnitSize": "10 stuks", "isBonus": False,
         "priceBeforeBonus": 3.49},
        # Already on the list: not suggested.
        {"webshopId": 111, "title": "AH Roomboter", "isBonus": False, "priceBeforeBonus": 3.29},
    ],
}

# GraphQL GetFavoriteStore, shaped like appie-go's API doc (dates around Tue 27 Oct 2026).
STORE = {"data": {"storesFavouriteStore": {
    "id": 1527,
    "address": {"street": "Nachtegaalstraat", "houseNumber": 48, "postalCode": "3581AD", "city": "Utrecht"},
    "openingDays": [
        {"date": "2026-10-26", "openingHour": {"openFrom": "08:00", "openUntil": "22:00"}},
        {"date": "2026-10-27", "openingHour": {"openFrom": "08:00", "openUntil": "22:00"}},
        {"date": "2026-10-28", "openingHour": {"openFrom": "08:00", "openUntil": "00:00"}},
        {"date": "2026-10-29", "openingHour": None},
    ],
    "geoLocation": {"latitude": 52.09, "longitude": 5.12},
    "phone": "030-2345678",
    "storeType": "AH",
    "services": [{"code": "PICKUP"}, {"code": "SELFSERVICE"}],
}}}

# GraphQL bargainItems, as in appie-go koopjes_test.go; the second one is a product we often buy.
BARGAINS = {"data": {"bargainItems": [
    {"product": {"id": 12345, "title": "AH Roodbaarsfilet", "brand": "AH", "salesUnitSize": "ca. 200 g"},
     "categoryTitle": "Vis",
     "markdown": {"markdownType": "PERCENTAGE", "markdownExpirationDate": "2026-10-28", "markdownPercentage": 35.0},
     "stock": 3, "bargainPrice": {"priceWas": "5.99", "priceNow": "3.89"}},
    {"product": {"id": 111, "title": "AH Roomboter", "brand": "AH", "salesUnitSize": "250 g"},
     "categoryTitle": "Zuivel",
     "markdown": {"markdownType": "PERCENTAGE", "markdownExpirationDate": "2026-10-27", "markdownPercentage": 35.0},
     "stock": 1, "bargainPrice": {"priceWas": "3.29", "priceNow": "2.14"}},
]}}


async def setup_appie(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="12345", data=TOKENS, title="Albert Heijn", options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
