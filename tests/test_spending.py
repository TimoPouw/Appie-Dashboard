"""Spending per month over the last year."""

from datetime import date

from homeassistant.core import HomeAssistant

from custom_components.appie.models import Receipt, monthly_totals

from .common import setup_appie


def test_monthly_totals_fills_empty_months_and_wraps_the_year() -> None:
    receipts = [
        Receipt("a", "2026-01-15T10:00:00", 10.0),
        Receipt("b", "2026-01-20T10:00:00", 5.5),
        Receipt("c", "2025-11-03T10:00:00", 20.0),
        Receipt("old", "2024-01-03T10:00:00", 99.0),
    ]
    months = monthly_totals(receipts, date(2026, 2, 10), months=4)
    assert [m["maand"] for m in months] == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert months[0] == {"maand": "2025-11", "naam": "nov 2025", "totaal": 20.0, "bonnen": 1}
    assert months[1]["totaal"] == 0 and months[1]["bonnen"] == 0
    assert months[2] == {"maand": "2026-01", "naam": "jan 2026", "totaal": 15.5, "bonnen": 2}


async def test_per_month_attribute(hass: HomeAssistant, api, freezer) -> None:
    freezer.move_to("2026-10-27T12:00:00+00:00")
    await setup_appie(hass)
    state = hass.states.get("sensor.albert_heijn_uitgaven_deze_maand")
    per_month = state.attributes["per_maand"]
    assert len(per_month) == 12
    by_month = {m["maand"]: m for m in per_month}
    # Test receipts: two in October 2026, one in September 2026.
    assert by_month["2026-10"]["totaal"] == 43.08 and by_month["2026-10"]["bonnen"] == 2
    assert by_month["2026-09"]["totaal"] == 50.0


async def test_history_fetched_once_a_day(hass: HomeAssistant, api, freezer) -> None:
    freezer.move_to("2026-10-27T12:00:00+00:00")
    entry = await setup_appie(hass)
    receipts = entry.runtime_data.receipts
    assert receipts._history_day is not None
    calls = api["get_receipts"].await_count
    await receipts.async_refresh()
    # Same day: one page for this month, no year of history again.
    assert api["get_receipts"].await_count == calls + 1
    assert receipts.data.per_month[-2]["totaal"] == 50.0  # September still known
