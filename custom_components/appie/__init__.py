"""Albert Heijn: shopping list, bonus and receipts from the AH app."""

from __future__ import annotations

from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import AppieClient
from .const import CONF_ACCESS_TOKEN, CONF_EXPIRES_AT, CONF_REFRESH_TOKEN, DOMAIN
from .coordinator import (
    AppieConfigEntry,
    AppieData,
    BargainsCoordinator,
    BonusBoxCoordinator,
    BonusCoordinator,
    DontForgetCoordinator,
    FavoriteListsCoordinator,
    FavoritesCoordinator,
    ListCoordinator,
    ListCostCoordinator,
    ReceiptsCoordinator,
    ReceiptViewerCoordinator,
    SpotlightCoordinator,
    StoreCoordinator,
)
from .receipt_pdf import ReceiptPdfView
from .services import async_setup_services

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SELECT, Platform.SENSOR, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services and the receipt PDF view."""
    async_setup_services(hass)
    hass.http.register_view(ReceiptPdfView())
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AppieConfigEntry) -> bool:
    """Set up Albert Heijn from a config entry."""

    def save_tokens(tokens: dict[str, Any]) -> None:
        # AH rotates refresh tokens: losing the new one means logging in again.
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: tokens["access_token"],
                CONF_REFRESH_TOKEN: tokens["refresh_token"],
                CONF_EXPIRES_AT: tokens["expires_at"],
            },
        )

    client = AppieClient(
        async_get_clientsession(hass),
        {
            "access_token": entry.data[CONF_ACCESS_TOKEN],
            "refresh_token": entry.data[CONF_REFRESH_TOKEN],
            "expires_at": entry.data.get(CONF_EXPIRES_AT, 0),
        },
        on_tokens=save_tokens,
    )
    shopping_list = ListCoordinator(hass, entry, client)
    bonus = BonusCoordinator(hass, entry, client, shopping_list)
    receipts = ReceiptsCoordinator(hass, entry, client)
    favorites = FavoritesCoordinator(hass, entry, client)
    list_cost = ListCostCoordinator(hass, entry, client, shopping_list)
    dont_forget = DontForgetCoordinator(hass, entry, client, shopping_list)
    store = StoreCoordinator(hass, entry, client)
    bargains = BargainsCoordinator(hass, entry, client, store, favorites)
    receipt_viewer = ReceiptViewerCoordinator(hass, entry, client, receipts)
    spotlight = SpotlightCoordinator(hass, entry, client)
    bonus_box = BonusBoxCoordinator(hass, entry, client, bonus)
    favorite_lists = FavoriteListsCoordinator(hass, entry, client)

    # Sequential on purpose: the first call may refresh the token.
    await shopping_list.async_config_entry_first_refresh()
    await bonus.async_config_entry_first_refresh()
    await receipts.async_config_entry_first_refresh()
    # Extras: a failure here leaves their entities unavailable, not the whole integration.
    await list_cost.async_refresh()
    await dont_forget.async_refresh()
    await store.async_refresh()
    await bargains.async_refresh()
    # Starts on the latest receipt, which the receipts coordinator already has: no call.
    await receipt_viewer.async_refresh()
    await spotlight.async_refresh()
    await bonus_box.async_refresh()
    await favorite_lists.async_refresh()

    for follower in (bonus, list_cost, dont_forget):
        entry.async_on_unload(shopping_list.async_add_listener(follower.list_changed))
    entry.async_on_unload(favorites.async_add_listener(bargains.favorites_changed))
    entry.async_on_unload(receipts.async_add_listener(receipt_viewer.receipts_changed))
    entry.runtime_data = AppieData(
        client=client,
        shopping_list=shopping_list,
        bonus=bonus,
        receipts=receipts,
        favorites=favorites,
        list_cost=list_cost,
        dont_forget=dont_forget,
        store=store,
        bargains=bargains,
        receipt_viewer=receipt_viewer,
        spotlight=spotlight,
        bonus_box=bonus_box,
        favorite_lists=favorite_lists,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # The first count reads ~100 receipts (15 s); don't hold up startup for it.
    entry.async_create_background_task(hass, favorites.async_refresh(), f"{entry.entry_id} favorites")
    entry.async_create_background_task(hass, _probe(client), "appie probe")
    return True


async def _probe(client: AppieClient) -> None:
    """TEMPORARY: log GraphQL validation errors (schema info only, no data)."""
    import logging

    log = logging.getLogger(__name__)
    fields = (
        "purchaseStampBalance paymentsGetFullBookletsCount milesBalance loyaltyPointsBalances loyaltyPrograms "
        "loyaltyChallenges paymentsGetGiftCards settlementsTotal recommendationsMissingBonus "
        "subscriptionCurrent subscriptionSummary subscriptionCalculateSavings subscriptionSavingsCarousel "
        "subscriptionEstimatedPremiumSavings subscriptionSavingPotential evalueAccountBalance"
    ).split()
    for name in fields:
        try:
            data = await client._request(
                "POST", "/graphql", {"query": f"query Probe {{ {name} {{ __typename }} }}", "variables": {}},
                graphql_errors=True,
            )
            errors = [e.get("message") for e in (data or {}).get("errors") or []]
            typename = ((data or {}).get("data") or {}).get(name)
            if isinstance(typename, list):
                typename = [i.get("__typename") for i in typename[:3] if isinstance(i, dict)] + [len(typename)]
            elif isinstance(typename, dict):
                typename = typename.get("__typename")
            log.warning("appie probe %s: errors=%s type=%s", name, errors, typename)
        except Exception as err:  # noqa: BLE001
            log.warning("appie probe %s: %s", name, str(err)[:300])


async def async_unload_entry(hass: HomeAssistant, entry: AppieConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
