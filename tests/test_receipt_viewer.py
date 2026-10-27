"""Looking at recent receipts: picker, picked-receipt sensor, PDF link and service."""

import base64

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.appie.api import AppieClient
from custom_components.appie.const import API_BASE, DOMAIN

from .common import TOKENS, setup_appie

LATEST = "zo 4 okt 2026 15:00 · € 36,16"
EARLIER = "za 3 okt 2026 09:00 · € 6,92"

DETAIL_R1 = {"data": {"posReceiptDetails": {
    "id": "r1",
    "products": [{"id": 5, "quantity": 1, "name": "AH KAAS", "price": None, "amount": {"amount": 6.92}}],
    "discounts": [],
    "payments": [{"method": "PINNEN", "amount": {"amount": 6.92}}],
}}}


async def test_picker_and_picked_receipt(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    await hass.async_block_till_done()
    picker = hass.states.get("select.albert_heijn_kassabon")
    assert picker.attributes["options"] == [LATEST, EARLIER, "wo 30 sep 2026 18:00 · € 50,00"]
    assert picker.state == LATEST

    picked = hass.states.get("sensor.albert_heijn_gekozen_kassabon")
    assert float(picked.state) == 36.16
    assert picked.attributes["receipt_id"] == "r2"
    assert picked.attributes["items"][0]["name"] == "Bio banaan"
    assert picked.attributes["pdf_url"].startswith("/api/appie/kassabon/r2?token=")

    # Picking an older one fetches it, once.
    calls = api["get_receipt_detail"].await_count
    api["get_receipt_detail"].return_value = DETAIL_R1
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.albert_heijn_kassabon", "option": EARLIER}, blocking=True
    )
    assert api["get_receipt_detail"].await_count == calls + 1
    assert api["get_receipt_detail"].await_args.args[0] == "r1"
    picked = hass.states.get("sensor.albert_heijn_gekozen_kassabon")
    assert float(picked.state) == 6.92
    assert picked.attributes["items"] == [{"name": "AH kaas", "quantity": 1, "amount": 6.92}]
    assert hass.states.get("select.albert_heijn_kassabon").state == EARLIER

    # Back to the latest: already known, no call.
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.albert_heijn_kassabon", "option": LATEST}, blocking=True
    )
    assert api["get_receipt_detail"].await_count == calls + 1


async def test_recent_has_id_and_pdf_link(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    recent = hass.states.get("sensor.albert_heijn_laatste_kassabon").attributes["recent"]
    assert [r["id"] for r in recent] == ["r2", "r1", "r0"]
    assert recent[0]["total"] == 36.16 and "datetime" in recent[0]
    assert recent[1]["pdf_url"].startswith("/api/appie/kassabon/r1?token=")


async def test_pdf_view(hass: HomeAssistant, api, hass_client_no_auth) -> None:
    await setup_appie(hass)
    url = hass.states.get("sensor.albert_heijn_laatste_kassabon").attributes["recent"][1]["pdf_url"]
    client = await hass_client_no_auth()

    resp = await client.get(url)
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "application/pdf"
    assert resp.headers["Cache-Control"] == "no-store"
    assert await resp.read() == b"%PDF-1.4 kassabon"
    api["get_receipt_pdf"].assert_awaited_once_with("r1")

    assert (await client.get("/api/appie/kassabon/r1?token=wrong")).status == 403
    assert (await client.get("/api/appie/kassabon/r1")).status == 403
    token = url.split("token=")[1]
    # Only the account's own receipts.
    assert (await client.get(f"/api/appie/kassabon/someone-else?token={token}")).status == 404
    assert api["get_receipt_pdf"].await_count == 1


async def test_get_receipt_service(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    latest = await hass.services.async_call(DOMAIN, "get_receipt", {}, blocking=True, return_response=True)
    assert latest["receipt_id"] == "r2" and latest["total"] == 36.16
    assert latest["discount_total"] == -0.7 and latest["payments"] == ["PINNEN"]

    api["get_receipt_detail"].return_value = DETAIL_R1
    older = await hass.services.async_call(
        DOMAIN, "get_receipt", {"receipt_id": "r1"}, blocking=True, return_response=True
    )
    assert older["items"] == [{"name": "AH kaas", "quantity": 1, "amount": 6.92}]
    assert older["pdf_url"].startswith("/api/appie/kassabon/r1?token=")

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "get_receipt", {"receipt_id": "nope"}, blocking=True, return_response=True
        )


async def test_get_receipt_pdf_decodes(hass: HomeAssistant, aioclient_mock) -> None:
    pdf = b"%PDF-1.4 echt"
    aioclient_mock.post(
        f"{API_BASE}/graphql", json={"data": {"posReceiptPdf": {"pdfBase64": base64.b64encode(pdf).decode()}}}
    )
    client = AppieClient(async_get_clientsession(hass), TOKENS)
    assert await client.get_receipt_pdf("r1") == pdf
    body = aioclient_mock.mock_calls[0][2]
    assert body["variables"] == {"id": "r1"}
    assert "posReceiptPdf" in body["query"]
