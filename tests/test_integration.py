"""Config flow, setup and the to-do entity against a mocked AH API."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.appie.api import AppieAuthError
from custom_components.appie.const import DOMAIN

from .common import TOKENS
from .common import setup_appie as _setup


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    with patch("custom_components.appie.config_flow.exchange_code", AsyncMock(side_effect=AppieAuthError)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"login_link": "appie://login-exit?code=old"}
        )
    assert result["errors"] == {"base": "code_expired"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"login_link": "nonsense link"})
    assert result["errors"] == {"base": "invalid_link"}

    with (
        patch("custom_components.appie.config_flow.exchange_code", AsyncMock(return_value=TOKENS)) as exchange,
        patch("custom_components.appie.async_setup_entry", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"login_link": "appie://login-exit?code=fresh123"}
        )
    assert exchange.await_args.args[1] == "fresh123"
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "12345"
    assert result["data"]["refresh_token"] == "r1"


async def test_setup_creates_entities(hass: HomeAssistant, api) -> None:
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    todo = hass.states.get("todo.albert_heijn_boodschappenlijst")
    assert todo.state == "3"  # three open items, milk is ticked off

    bonus = hass.states.get("sensor.albert_heijn_bonus_voor_ons")
    assert bonus.state == "4"
    assert bonus.attributes["offers"][0]["title"] == "AH Courgette"
    assert bonus.attributes["period_end"] == "2026-10-11"

    receipt = hass.states.get("sensor.albert_heijn_laatste_kassabon")
    assert float(receipt.state) == 36.16
    assert receipt.attributes["items"][0]["name"] == "Bio banaan"

    month = hass.states.get("sensor.albert_heijn_uitgaven_deze_maand")
    assert month.attributes["state_class"] == "total"


async def test_todo_actions(hass: HomeAssistant, api) -> None:
    await _setup(hass)
    entity = "todo.albert_heijn_boodschappenlijst"

    await hass.services.async_call("todo", "add_item", {"item": "Kaas"}, target={"entity_id": entity}, blocking=True)
    assert api["patch_list"].await_args.args[0] == [
        {"description": "Kaas", "searchTerm": "Kaas", "type": "SHOPPABLE", "originCode": "TXT",
         "quantity": 1, "strikeThrough": False}
    ]

    await hass.services.async_call("todo", "add_item", {"item": "441199"}, target={"entity_id": entity}, blocking=True)
    assert api["patch_list"].await_args.args[0][0]["productId"] == 441199

    await hass.services.async_call(
        "todo", "update_item", {"item": "AH Roomboter", "status": "completed"},
        target={"entity_id": entity}, blocking=True,
    )
    body = api["patch_list"].await_args.args[0]
    assert body == [{"description": "AH Roomboter", "searchTerm": "AH Roomboter", "type": "SHOPPABLE",
                     "originCode": "PRD", "quantity": 1, "strikeThrough": True, "productId": 111}]

    await hass.services.async_call(
        "todo", "remove_item", {"item": "AH Courgette"}, target={"entity_id": entity}, blocking=True
    )
    assert api["patch_list"].await_args.args[0][0]["quantity"] == 0

    # Adding text that is already on the list (ticked off) re-opens it instead of duplicating.
    await hass.services.async_call("todo", "add_item", {"item": "Melk"}, target={"entity_id": entity}, blocking=True)
    body = api["patch_list"].await_args.args[0]
    assert body[0]["description"] == "Melk" and body[0]["strikeThrough"] is False


async def test_auth_failure_starts_reauth(hass: HomeAssistant, api) -> None:
    api["get_list"].side_effect = AppieAuthError("expired")
    entry = MockConfigEntry(domain=DOMAIN, unique_id="12345", data=TOKENS)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_favorite_buttons(hass: HomeAssistant, api) -> None:
    await _setup(hass)
    await hass.async_block_till_done()

    first = hass.states.get("button.albert_heijn_vaak_gekocht_1")
    second = hass.states.get("button.albert_heijn_vaak_gekocht_2")
    assert hass.states.get("button.albert_heijn_vaak_gekocht_3").state == "unavailable"
    # Both products are on all three receipts; the banana is not sold online -> text.
    names = {first.attributes["title"], second.attributes["title"]}
    assert names == {"Bio banaan", "AH Roomboter"}
    butter = first if first.attributes["title"] == "AH Roomboter" else second
    banana = second if butter is first else first
    assert butter.attributes["on_list"] is True and butter.attributes["quantity_on_list"] == 1

    # Already on the list: one more.
    await hass.services.async_call("button", "press", {"entity_id": butter.entity_id}, blocking=True)
    body = api["patch_list"].await_args.args[0][0]
    assert body["productId"] == 111 and body["quantity"] == 2

    # Not on the list: added as free text.
    await hass.services.async_call("button", "press", {"entity_id": banana.entity_id}, blocking=True)
    body = api["patch_list"].await_args.args[0][0]
    assert body == {"description": "Bio banaan", "searchTerm": "Bio banaan", "type": "SHOPPABLE",
                    "originCode": "TXT", "quantity": 1, "strikeThrough": False}
