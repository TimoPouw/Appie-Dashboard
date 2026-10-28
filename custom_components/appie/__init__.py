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
    SavingsCoordinator,
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
    savings = SavingsCoordinator(hass, entry, client, receipts)

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
    await savings.async_refresh()

    for follower in (bonus, list_cost, dont_forget):
        entry.async_on_unload(shopping_list.async_add_listener(follower.list_changed))
    entry.async_on_unload(favorites.async_add_listener(bargains.favorites_changed))
    entry.async_on_unload(receipts.async_add_listener(receipt_viewer.receipts_changed))
    savings.receipts_changed()
    entry.async_on_unload(receipts.async_add_listener(savings.receipts_changed))
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
        savings=savings,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # The first count reads ~100 receipts (15 s); don't hold up startup for it.
    entry.async_create_background_task(hass, favorites.async_refresh(), f"{entry.entry_id} favorites")
    entry.async_create_background_task(hass, _probe(client), "appie probe")
    return True


async def _probe(client: AppieClient) -> None:
    """TEMPORARY: find 'mijn verrekeningen' (schema suggestions only, read-only)."""
    import logging

    log = logging.getLogger(__name__)
    queries = {
        # Unknown names: AH's "Did you mean" lists fields added after the schema dump.
        "f_settlements": "{ settlements { __typename } }",
        "f_wallet": "{ wallet { __typename } }",
        "f_walletOverview": "{ walletOverview { __typename } }",
        "f_settlement": "{ settlement { __typename } }",
        "f_customerCareSettlements": "{ customerCareSettlements { __typename } }",
        "f_evalue": "{ evalue { __typename } }",
        "f_evalueBalance": "{ evalueBalance { __typename } }",
        "f_memberWallet": "{ memberWallet { __typename } }",
        "f_settlementsBalance": "{ settlementsBalance { __typename } }",
        "f_balances": "{ balances { __typename } }",
        # Misspelled arguments: AH may suggest the real ones.
        "a_page": "{ customerCareSettlementsPage(ordrId: 1) { __typename } }",
        "a_total": "{ settlementsTotal(ordrId: 1) { __typename } }",
        "a_page2": "{ customerCareSettlementsPage(typ: 1) { __typename } }",
        "a_total2": "{ settlementsTotal(statu: 1) { __typename } }",
        "a_total3": "{ settlementsTotal(memberI: 1) { __typename } }",
        "history": '{ evalueTransactionHistory(accountType: "SETTLEMENT", pagination: {offset: 0, limit: 5}) { __typename } }',
    }
    for kind in ("COMPENSATION", "CUSTOMER_SERVICE", "CUSTOMERCARE", "CUSTOMER_CARE", "VOUCHER", "GOODWILL", "ONLINE",
                 "ECOM", "WEBSHOP", "ORDER", "evalue", "default", "settlements", "ah", "AH_EVALUE", "NEXT_ORDER"):
        queries[f"evalue_{kind}"] = f'{{ evalueAccountBalance(accountType: "{kind}") {{ value {{ amount }} }} }}'
    for name, query in queries.items():
        try:
            data = await client._request("POST", "/graphql", {"query": "query Probe " + query, "variables": {}}, graphql_errors=True)
            errors = [e.get("message") for e in (data or {}).get("errors") or []]
            log.warning("appie probe %s: errors=%s data=%s", name, errors, str((data or {}).get("data"))[:300])
        except Exception as err:  # noqa: BLE001
            log.warning("appie probe %s: %s", name, str(err)[:300])


async def async_unload_entry(hass: HomeAssistant, entry: AppieConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
