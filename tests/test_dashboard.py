"""The shipped dashboard: every entity exists and every markdown template renders."""

import re
from pathlib import Path

import pytest
import yaml

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from .common import setup_appie

DASHBOARD = Path(__file__).parents[1] / "dashboards/appie.yaml"


def _cards(node):
    if isinstance(node, dict):
        if "type" in node and node.get("type") not in ("sections", "grid"):
            yield node
        for value in node.values():
            yield from _cards(value)
    elif isinstance(node, list):
        for value in node:
            yield from _cards(value)


@pytest.fixture
def dashboard() -> dict:
    return yaml.safe_load(DASHBOARD.read_text())


async def test_dashboard_entities_exist(hass: HomeAssistant, api, dashboard) -> None:
    await setup_appie(hass)
    await hass.async_block_till_done()
    text = DASHBOARD.read_text()
    referenced = set(re.findall(r"\b(?:sensor|binary_sensor|button|select|todo)\.albert_heijn_\w+", text))
    assert referenced
    # The ten default "vaak gekocht" buttons exist even when fewer products are known yet.
    missing = {e for e in referenced if hass.states.get(e) is None}
    assert not missing


async def test_dashboard_templates_render(hass: HomeAssistant, api, dashboard) -> None:
    await setup_appie(hass)
    await hass.async_block_till_done()
    markdown = [c["content"] for c in _cards(dashboard) if c.get("type") == "markdown"]
    assert len(markdown) >= 9
    rendered = [Template(content, hass).async_render(parse_result=False) for content in markdown]
    joined = "\n".join(rendered)
    # Real data shows up, not just the empty-state texts.
    for expected in ("AH Goudse jong 48+ plakken", "Weekboodschappen", "AH Courgette", "AH Pancakes",
                     "Nachtegaalstraat", "AH Roodbaarsfilet", "Bio banaan", "PDF"):
        assert expected in joined, expected
    assert "{{" not in joined and "{%" not in joined


async def test_dashboard_templates_without_data(hass: HomeAssistant, dashboard) -> None:
    """Before the integration is set up (or while it's unavailable) nothing breaks."""
    markdown = [c["content"] for c in _cards(dashboard) if c.get("type") == "markdown"]
    for content in markdown:
        Template(content, hass).async_render(parse_result=False)
