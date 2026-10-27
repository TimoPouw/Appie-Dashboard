"""Recommended recipes and recipe search."""

from homeassistant.core import HomeAssistant

from custom_components.appie.const import DOMAIN
from custom_components.appie.models import parse_recommended_recipes

from .common import setup_appie


async def test_recipes_sensor(hass: HomeAssistant, api) -> None:
    entry = await setup_appie(hass)
    assert entry.runtime_data.recipes.update_interval.total_seconds() == 24 * 3600
    state = hass.states.get("sensor.albert_heijn_recepten")
    assert state.state == "2"
    assert state.attributes["recepten"] == [
        # Recommended and also a bonus recipe: listed once, marked bonus.
        {"id": 12345, "title": "Pasta carbonara", "tijd": 25, "image": "https://img.invalid/445",
         "nutriscore": "B", "bonus": True},
        {"id": 777, "title": "Traybake met kip", "tijd": 40, "image": None, "nutriscore": "A", "bonus": True},
    ]


def test_generic_recipes_only_as_fallback() -> None:
    raw = {"data": {"recommendations": {
        "recipeRecommendations": [], "bonusRecipes": [],
        "genericRecipeRecommendations": [{"recipe": {"id": 1, "title": "Generiek", "time": {"cook": 10}}}],
    }}}
    assert [r.title for r in parse_recommended_recipes(raw)] == ["Generiek"]
    assert parse_recommended_recipes({"data": {"recommendations": None}}) == []


async def test_search_recipes_service(hass: HomeAssistant, api) -> None:
    await setup_appie(hass)
    response = await hass.services.async_call(
        DOMAIN, "search_recipes", {"zoekterm": " pasta ", "aantal": 1}, blocking=True, return_response=True
    )
    api["search_recipes"].assert_awaited_with("pasta", 1)
    assert response == {
        "recepten": [{"id": 12345, "title": "Pasta carbonara", "tijd": 25, "image": "https://img.invalid/445",
                      "nutriscore": "B", "bonus": False}],
        "totaal": 245,
    }
