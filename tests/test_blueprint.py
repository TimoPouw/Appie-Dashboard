"""The koopje blueprint: valid, and it reacts to appie_koopje_favoriet."""

import shutil
from pathlib import Path

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

BLUEPRINT = Path(__file__).parents[1] / "blueprints/automation/appie/koopje_favoriet.yaml"


async def test_koopje_blueprint(hass: HomeAssistant) -> None:
    target = Path(hass.config.path("blueprints/automation/appie"))
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT, target / "koopje_favoriet.yaml")

    assert await async_setup_component(hass, "persistent_notification", {})
    assert await async_setup_component(
        hass,
        "automation",
        {"automation": {"id": "koopje", "alias": "Koopje", "use_blueprint": {
            "path": "appie/koopje_favoriet.yaml", "input": {}}}},
    )
    await hass.async_block_till_done()
    assert hass.states.get("automation.koopje").state == "on"

    hass.bus.async_fire("appie_koopje_favoriet", {
        "product_id": 111, "title": "AH Roomboter", "size": "250 g", "price": 2.14, "price_was": 3.29,
        "expires": "2026-10-27",
    })
    await hass.async_block_till_done()
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    texts = [n["message"] for n in notifications.values()]
    assert texts == ["AH Roomboter (250 g) voor € 2.14 in plaats van € 3.29."]
