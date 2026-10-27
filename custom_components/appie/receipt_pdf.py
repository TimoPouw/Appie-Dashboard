"""Serve a receipt's PDF from AH when it is opened; nothing is kept."""

from __future__ import annotations

import hmac
import logging

from aiohttp import web

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState

from .api import AppieError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class ReceiptPdfView(HomeAssistantView):
    """GET /api/appie/kassabon/<id>?token=...

    Opened from a dashboard link, so without HA's bearer header: the token in
    the link (random, in memory, new on every start) stands in for it, as with
    camera images. Only receipts of the account itself are served.
    """

    url = f"/api/{DOMAIN}/kassabon/{{receipt_id}}"
    name = f"api:{DOMAIN}:kassabon"
    requires_auth = False

    async def get(self, request: web.Request, receipt_id: str) -> web.StreamResponse:
        hass = request.app[KEY_HASS]
        token = request.query.get("token", "")
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is not ConfigEntryState.LOADED:
                continue
            viewer = entry.runtime_data.receipt_viewer
            if not token or not hmac.compare_digest(token, viewer.pdf_token):
                continue
            receipt = viewer.find(receipt_id)
            if receipt is None:
                return web.Response(status=404)
            try:
                pdf = await entry.runtime_data.client.get_receipt_pdf(receipt_id)
            except AppieError as err:
                _LOGGER.warning("receipt pdf: %s", err)
                return web.Response(status=502)
            return web.Response(
                body=pdf,
                content_type="application/pdf",
                headers={
                    "Content-Disposition": f'inline; filename="kassabon-{receipt.when[:10]}.pdf"',
                    "Cache-Control": "no-store",
                },
            )
        return web.Response(status=403)
