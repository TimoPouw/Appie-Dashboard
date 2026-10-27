"""Koopzegels, Air Miles, spaaracties, uitdagingen, Premium, tegoeden and gemiste bonus."""

import logging
from datetime import date

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.appie.api import PREMIUM_TYPE, AppieClient, AppieError
from custom_components.appie.const import API_BASE
from custom_components.appie.models import (
    add_program_balances,
    current_programs,
    parse_gift_cards,
    parse_premium,
    parse_purchase_stamps,
    parse_settlements,
)

from .common import LOYALTY, STAMPS, TOKENS, WALLET, setup_appie
from .test_models import LIST


def test_parse_purchase_stamps() -> None:
    assert parse_purchase_stamps(STAMPS) == {
        "zegels": 212,
        "volle_boekjes": 1,
        "in_huidig_boekje": 32,
        "zegels_per_boekje": 180,
        "zegels_half_boekje": 90,
        "prijs_per_zegel": 0.1,
        "rente_vol_boekje": 0.54,
        "ingelegd": 21.2,
        "rente": 0.54,
        "uitbetaling": 21.74,
    }
    assert parse_purchase_stamps(None) is None


def test_current_programs_skip_ended_and_get_points() -> None:
    programs = current_programs(LOYALTY["loyaltyPrograms"], date(2026, 10, 27))
    assert [p["id"] for p in programs] == [7]
    assert programs[0]["naam"] == "Spaar voor pannen" and programs[0]["per_kaart"] == 30
    assert programs[0]["punten"] is None
    assert add_program_balances(programs, [{"programId": 7, "balance": 12}])[0]["punten"] == 12
    # Not started yet: left out too.
    assert current_programs(LOYALTY["loyaltyPrograms"], date(2026, 9, 1)) == []


def test_premium_without_subscription() -> None:
    parsed = parse_premium({"subscriptionCurrent": None, "subscriptionSavingPotential": {"premiumSavingPotential": 50}})
    assert parsed["actief"] is False and parsed["mogelijke_besparing"] == 50.0
    assert parse_premium({}) is None


def test_gift_card_number_is_masked() -> None:
    cards = parse_gift_cards(WALLET["paymentsGetGiftCards"])
    assert cards == [{"kaart": "•••• 7890", "saldo": 25.0, "status": "ACTIVE", "sinds": "2026-05-01T10:00:00Z"}]
    assert parse_settlements(WALLET["settlementsTotal"]) == {"totaal": 3.5, "aantal": 1}
    assert parse_settlements({"totalAmount": None, "settlements": None}) == {"totaal": 0.0, "aantal": 0}


async def test_savings_sensors(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)

    stamps = hass.states.get("sensor.albert_heijn_koopzegels")
    assert stamps.state == "212"
    assert stamps.attributes["volle_boekjes"] == 1 and stamps.attributes["zegels_per_boekje"] == 180
    assert hass.states.get("sensor.albert_heijn_koopzegels_waarde").state == "21.74"
    assert hass.states.get("sensor.albert_heijn_air_miles").state == "1234"

    programs = hass.states.get("sensor.albert_heijn_spaaracties")
    assert programs.state == "1" and programs.attributes["met_punten"] == 1
    assert programs.attributes["acties"][0]["punten"] == 12
    api["get_loyalty_balances"].assert_awaited_with([7])

    challenges = hass.states.get("sensor.albert_heijn_uitdagingen")
    assert challenges.state == "1"
    assert challenges.attributes["uitdagingen"][0]["stappen"][0] == {
        "label": "Koop fruit", "omschrijving": "3 keer", "status": "IN_PROGRESS", "voortgang": 1, "doel": 3,
        "van": "2026-10-20", "tot": "2099-01-01",
    }

    premium = hass.states.get("sensor.albert_heijn_premium")
    assert premium.state == "actief" and premium.attributes["eind"] == "2026-12-31"
    assert hass.states.get("sensor.albert_heijn_premium_besparing").state == "123.46"

    gift = hass.states.get("sensor.albert_heijn_cadeaukaarten")
    assert gift.state == "25.0" and gift.attributes["aantal"] == 1
    assert "6299001234567890" not in str(gift.attributes)
    assert hass.states.get("sensor.albert_heijn_openstaand_tegoed").state == "3.5"


async def test_one_failing_part_leaves_the_rest(hass: HomeAssistant, api) -> None:
    api["get_miles"].side_effect = AppieError("graphql: Subgraph errors redacted")
    api["get_premium"].return_value = {"subscriptionCurrent": None, "subscriptionSavingPotential": {"premiumSavingPotential": 50}}
    entry = await setup_appie(hass)
    assert hass.states.get("sensor.albert_heijn_air_miles").state == "unavailable"
    assert hass.states.get("sensor.albert_heijn_koopzegels").state == "212"
    # Premium answered, but there is no subscription.
    assert hass.states.get("sensor.albert_heijn_premium").state == "niet actief"
    assert hass.states.get("sensor.albert_heijn_premium_besparing").state == "unknown"

    # A later failure keeps the last known value instead of flapping.
    api["get_purchase_stamps"].side_effect = AppieError("timeout")
    await entry.runtime_data.savings.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.albert_heijn_koopzegels").state == "212"


async def test_new_receipt_refreshes_savings(hass: HomeAssistant, api) -> None:
    entry = await setup_appie(hass)
    calls = api["get_purchase_stamps"].await_count

    # Same receipts: nothing to do.
    await entry.runtime_data.receipts.async_refresh()
    await hass.async_block_till_done()
    assert api["get_purchase_stamps"].await_count == calls

    receipts = api["get_receipts"].return_value
    newest = {**receipts["data"]["posReceiptsPage"]["posReceipts"][0], "id": "nieuw"}
    api["get_receipts"].return_value = {
        "data": {"posReceiptsPage": {"posReceipts": [newest, *receipts["data"]["posReceiptsPage"]["posReceipts"]]}}
    }
    await entry.runtime_data.receipts.async_refresh()
    await hass.async_block_till_done()
    assert api["get_purchase_stamps"].await_count == calls + 1


async def test_missed_bonus(hass: HomeAssistant, api) -> None:
    api["get_products"].return_value = {
        111: {"webshopId": 111, "title": "AH Roomboter", "images": [], "isBonus": True, "bonusMechanism": "2e halve prijs"}
    }
    entry = await setup_appie(hass)
    await hass.async_block_till_done()
    # In the bonus, but already on the list.
    assert hass.states.get("sensor.albert_heijn_gemiste_bonus").state == "0"

    api["get_list"].return_value = {"items": [i for i in LIST["items"] if i.get("productDetails", {})
                                              .get("product", {}).get("webshopId") != 111]}
    await entry.runtime_data.shopping_list.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.albert_heijn_gemiste_bonus")
    assert state.state == "1"
    assert state.attributes["producten"][0]["title"] == "AH Roomboter"
    assert state.attributes["producten"][0]["bonus"] == "2e halve prijs"


async def test_api_premium_query_and_partial_result(hass: HomeAssistant, aioclient_mock, caplog) -> None:
    aioclient_mock.post(
        f"{API_BASE}/graphql",
        json={
            "data": {"subscriptionCurrent": None, "subscriptionSavingPotential": {"premiumSavingPotential": 12.5}},
            "errors": [{"message": "Subgraph errors redacted"}],
        },
    )
    client = AppieClient(async_get_clientsession(hass), TOKENS)
    data = await client.get_premium()
    assert data["subscriptionSavingPotential"] == {"premiumSavingPotential": 12.5}
    body = aioclient_mock.mock_calls[0][2]
    assert body["variables"] == {"type": PREMIUM_TYPE}
    assert "subscriptionCurrent(type: $type)" in body["query"]


async def test_api_wallet_is_read_only_and_redacted(hass: HomeAssistant, aioclient_mock, caplog) -> None:
    aioclient_mock.post(f"{API_BASE}/graphql", json={"data": WALLET})
    client = AppieClient(async_get_clientsession(hass), TOKENS)
    with caplog.at_level(logging.DEBUG, logger="custom_components.appie.api"):
        data = await client.get_wallet()
    assert data == WALLET
    query = aioclient_mock.mock_calls[0][2]["query"]
    assert query.lstrip().startswith("query ") and "mutation" not in query
    assert "6299001234567890" not in caplog.text


async def test_api_errors_without_data_raise(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(f"{API_BASE}/graphql", json={"errors": [{"message": "nope"}]})
    client = AppieClient(async_get_clientsession(hass), TOKENS)
    try:
        await client.get_purchase_stamps()
    except AppieError as err:
        assert "nope" in str(err)
    else:
        raise AssertionError("expected AppieError")
