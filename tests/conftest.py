"""Shared fixtures."""

from unittest.mock import AsyncMock, patch

import pytest

from .common import (
    BARGAINS,
    DONT_FORGET,
    META,
    RECIPE_SEARCH,
    RECOMMENDED_RECIPES,
    SEARCH,
    STORE,
    TOTAL_PRICE,
)
from .test_models import DETAIL, LIST, PERSONAL, PREVIOUS, RECEIPTS


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/appie in every test."""
    yield


@pytest.fixture
def api():
    """Patch every AppieClient call; no test talks to api.ah.nl."""
    client = "custom_components.appie.api.AppieClient"
    mocks = {
        "get_list": AsyncMock(return_value=LIST),
        "patch_list": AsyncMock(),
        "get_bonus_metadata": AsyncMock(return_value=META),
        "get_personal_bonus": AsyncMock(return_value=PERSONAL),
        "get_previously_bought_bonus": AsyncMock(return_value=PREVIOUS),
        "get_receipts": AsyncMock(return_value=RECEIPTS),
        "get_receipt_detail": AsyncMock(return_value=DETAIL),
        "convert_pos_ids": AsyncMock(return_value={1: -1, 2: 111}),
        "get_products": AsyncMock(return_value={111: {"webshopId": 111, "title": "AH Roomboter", "images": []}}),
        "search_products": AsyncMock(return_value=SEARCH),
        "get_total_price": AsyncMock(return_value=TOTAL_PRICE),
        "get_dont_forget": AsyncMock(return_value=DONT_FORGET),
        "get_favorite_store": AsyncMock(return_value=STORE),
        "get_bargains": AsyncMock(return_value=BARGAINS),
        "get_recommended_recipes": AsyncMock(return_value=RECOMMENDED_RECIPES),
        "search_recipes": AsyncMock(return_value=RECIPE_SEARCH),
    }
    patches = [patch(f"{client}.{name}", mock) for name, mock in mocks.items()]
    patches.append(patch("custom_components.appie.coordinator.FAVORITES_DAYS", 100_000))
    for p in patches:
        p.start()
    yield mocks
    for p in reversed(patches):
        p.stop()
