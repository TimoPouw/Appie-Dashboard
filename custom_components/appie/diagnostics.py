"""Diagnostics with the tokens and personal details left out."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .api import REDACT_KEYS
from .const import CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN
from .coordinator import AppieConfigEntry

# Tokens, plus member and address fields wherever they turn up in new data.
TO_REDACT = {CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, *REDACT_KEYS} - {"name"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: AppieConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data
    receipts = data.receipts.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "list": [asdict(i) for i in data.shopping_list.data or []],
        "bonus": asdict(data.bonus.data) if data.bonus.data else None,
        "favorites": [asdict(f) for f in data.favorites.data or []],
        "list_cost": asdict(data.list_cost.data) if data.list_cost.data else None,
        "dont_forget": [asdict(s) for s in data.dont_forget.data or []],
        # The store address says roughly where the member lives.
        "store": async_redact_data(asdict(data.store.data), TO_REDACT) if data.store.data else None,
        "bargains": [asdict(b) for b in data.bargains.data or []],
        "recipes": len(data.recipes.data or []),
        "receipts": {
            "count": len(receipts.receipts),
            "month_total": receipts.month_total,
            "latest_items": len(receipts.latest_detail.items) if receipts.latest_detail else 0,
        }
        if receipts
        else None,
    }
