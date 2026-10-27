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
    BonusCoordinator,
    DontForgetCoordinator,
    FavoritesCoordinator,
    ListCoordinator,
    ListCostCoordinator,
    ReceiptsCoordinator,
    ReceiptViewerCoordinator,
    RecipesCoordinator,
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
    recipes = RecipesCoordinator(hass, entry, client)
    receipt_viewer = ReceiptViewerCoordinator(hass, entry, client, receipts)

    # Sequential on purpose: the first call may refresh the token.
    await shopping_list.async_config_entry_first_refresh()
    await bonus.async_config_entry_first_refresh()
    await receipts.async_config_entry_first_refresh()
    # Extras: a failure here leaves their entities unavailable, not the whole integration.
    await list_cost.async_refresh()
    await dont_forget.async_refresh()
    await store.async_refresh()
    await bargains.async_refresh()
    await recipes.async_refresh()
    # Starts on the latest receipt, which the receipts coordinator already has: no call.
    await receipt_viewer.async_refresh()

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
        recipes=recipes,
        receipt_viewer=receipt_viewer,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # The first count reads ~100 receipts (15 s); don't hold up startup for it.
    entry.async_create_background_task(hass, favorites.async_refresh(), f"{entry.entry_id} favorites")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AppieConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
