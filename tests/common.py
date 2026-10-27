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


async def setup_appie(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="12345", data=TOKENS, title="Albert Heijn", options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
