"""Async client for the (unofficial) Albert Heijn mobile API.

Endpoints and headers follow gwillem/appie-go (AGPL-3.0) and were checked
against a live account. Calls added later are marked in their docstring:
(verified) when endpoint and payload are taken literally from appie-go,
(inferred) when they rest on an assumption, which is then explained.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .const import (
    API_BASE,
    APPLICATION,
    CLIENT_ID,
    CLIENT_VERSION,
    TOKEN_REFRESH_MARGIN,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=30)

RECEIPTS_QUERY = """query FetchPosReceipts($offset: Int!, $limit: Int!) {
  posReceiptsPage(pagination: {offset: $offset, limit: $limit}) {
    posReceipts { id dateTime totalAmount { amount } }
  }
}"""

RECEIPT_DETAIL_QUERY = """query FetchReceipt($id: String!) {
  posReceiptDetails(id: $id) {
    id
    products { id quantity name price { amount } amount { amount } }
    discounts { name amount { amount } }
    payments { method amount { amount } }
  }
}"""


# Left out of debug logging: credentials and anything that identifies the member.
REDACT_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "accessToken",
        "refreshToken",
        "id_token",
        "code",
        "address",
        "addressInvoice",
        "street",
        "houseNumber",
        "houseNumberExtra",
        "postalCode",
        "zipCode",
        "zipCodeExtra",
        "geoLocation",
        "emailAddress",
        "phoneNumber",
        "dateOfBirth",
        "name",
        "cards",
        "memberId",
        "analytics",
    }
)
# Product and store names are fine to log; "name" is only personal on a member.
_NAMED_THINGS = frozenset({"products", "product", "productCards", "posReceiptDetails", "result"})
_LOG_LIMIT = 2000


def redact(data: Any, parent: str | None = None) -> Any:
    """Copy of an API response that is safe to put in a debug log."""
    if isinstance(data, dict):
        return {
            key: "**REDACTED**"
            if key in REDACT_KEYS and not (key == "name" and parent in _NAMED_THINGS)
            else redact(value, key)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact(value, parent) for value in data]
    return data


# appie-go doc/albertheijn_api.md, "FetchTotalPrice".
TOTAL_PRICE_QUERY = """query FetchTotalPrice($products: [PriceLineItem!]!) {
  totalPrice(products: $products) {
    __typename
    withoutDiscount { __typename amount }
    discount { __typename amount }
  }
}"""


class AppieError(Exception):
    """API call failed."""


class AppieAuthError(AppieError):
    """Tokens are no longer valid; the user has to log in again."""


def extract_code(text: str) -> str:
    """Pull the login code out of a pasted appie://login-exit?code=... URL."""
    text = text.strip()
    if match := re.search(r"[?&]code=([^&\s]+)", text):
        return match.group(1)
    if re.fullmatch(r"[\w\-.~%]+", text):
        return text
    raise ValueError("no code found")


def _headers(access_token: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "x-client-name": CLIENT_ID,
        "x-client-version": CLIENT_VERSION,
        "x-application": APPLICATION,
        "x-accept-language": "nl-NL",
        "x-correlation-id": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


async def exchange_code(session: aiohttp.ClientSession, code: str) -> dict[str, Any]:
    """Trade a one-time login code for tokens."""
    return await _token_call(session, "/mobile-auth/v1/auth/token", {"clientId": CLIENT_ID, "code": code})


async def _token_call(session: aiohttp.ClientSession, path: str, body: dict) -> dict[str, Any]:
    try:
        async with session.post(API_BASE + path, json=body, headers=_headers(), timeout=TIMEOUT) as resp:
            if resp.status in (400, 401, 403):
                raise AppieAuthError(f"token request refused ({resp.status})")
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    except AppieAuthError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise AppieError(f"token request failed: {err}") from err
    if not data or "access_token" not in data:
        raise AppieAuthError("no access token in response")
    data["expires_at"] = time.time() + float(data.get("expires_in") or 0)
    return data


def member_id(access_token: str) -> str:
    """Access tokens look like '<member id>_<uuid>'."""
    return access_token.split("_", 1)[0]


class AppieClient:
    """Authenticated client. Persist tokens through on_tokens."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: dict[str, Any],
        on_tokens: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> None:
        self._session = session
        self._tokens = dict(tokens)
        self._on_tokens = on_tokens
        self._lock = asyncio.Lock()

    @property
    def tokens(self) -> dict[str, Any]:
        return dict(self._tokens)

    async def _ensure_token(self, rejected: str | None = None) -> str:
        """Return a valid access token, refreshing when (nearly) expired.

        rejected: a token the API just answered 401 to; refresh unless another
        call already replaced it. AH rotates refresh tokens, hence the lock.
        """
        async with self._lock:
            expires_at = float(self._tokens.get("expires_at") or 0)
            stale = time.time() > expires_at - TOKEN_REFRESH_MARGIN.total_seconds()
            if stale or rejected == self._tokens["access_token"]:
                new = await _token_call(
                    self._session,
                    "/mobile-auth/v1/auth/token/refresh",
                    {"clientId": CLIENT_ID, "refreshToken": self._tokens["refresh_token"]},
                )
                self._tokens = {
                    "access_token": new["access_token"],
                    "refresh_token": new["refresh_token"],
                    "expires_at": new["expires_at"],
                }
                if self._on_tokens:
                    result = self._on_tokens(self.tokens)
                    if asyncio.iscoroutine(result):
                        await result
                _LOGGER.debug("access token refreshed")
            return self._tokens["access_token"]

    async def _request(self, method: str, path: str, body: Any = None) -> Any:
        token = await self._ensure_token()
        for attempt in (1, 2):
            try:
                async with self._session.request(
                    method, API_BASE + path, json=body, headers=_headers(token), timeout=TIMEOUT
                ) as resp:
                    if resp.status == 401 and attempt == 1:
                        token = await self._ensure_token(rejected=token)
                        continue
                    if resp.status in (401, 403):
                        raise AppieAuthError(f"{method} {path}: {resp.status}")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise AppieError(f"{method} {path}: HTTP {resp.status} {text[:200]}")
                    text = await resp.text()
                    data = await resp.json(content_type=None) if text else None
                    if _LOGGER.isEnabledFor(logging.DEBUG):
                        _LOGGER.debug(
                            "%s %s -> %s %s", method, path.split("?")[0], resp.status, str(redact(data))[:_LOG_LIMIT]
                        )
                    return data
            except asyncio.TimeoutError as err:
                # AH occasionally stalls a single request; one retry is enough.
                if attempt == 2:
                    raise AppieError(f"{method} {path}: timeout") from err
            except aiohttp.ClientError as err:
                raise AppieError(f"{method} {path}: {err}") from err
        raise AppieError(f"{method} {path}: failed")

    async def _graphql(self, query: str, variables: dict[str, Any]) -> dict:
        data = await self._request("POST", "/graphql", {"query": query, "variables": variables})
        if errors := (data or {}).get("errors"):
            raise AppieError(f"graphql: {errors[0].get('message')}")
        return data

    # shopping list

    async def get_list(self) -> dict:
        return await self._request("GET", "/mobile-services/shoppinglist/v2/items")

    async def patch_list(self, items: list[dict]) -> None:
        await self._request("PATCH", "/mobile-services/shoppinglist/v2/items", {"items": items})

    # bonus

    async def get_bonus_metadata(self) -> dict:
        return await self._request("GET", "/mobile-services/bonuspage/v3/metadata")

    async def get_personal_bonus(self, bonus_start: str) -> dict:
        return await self._request("GET", f"/mobile-services/bonuspage/v1/personal?bonusStartDate={bonus_start}")

    async def get_previously_bought_bonus(self, day: date) -> dict:
        return await self._request(
            "GET",
            f"/mobile-services/bonuspage/v2/section/previously-bought?application={APPLICATION}&date={day.isoformat()}",
        )

    # receipts

    async def get_receipts(self, offset: int, limit: int) -> dict:
        return await self._graphql(RECEIPTS_QUERY, {"offset": offset, "limit": limit})

    async def get_receipt_detail(self, receipt_id: str) -> dict:
        return await self._graphql(RECEIPT_DETAIL_QUERY, {"id": receipt_id})

    # products

    async def convert_pos_ids(self, pos_ids: list[int]) -> dict[int, int]:
        """Till product ids -> webshop ids (-1 when AH has no online product)."""
        if not pos_ids:
            return {}
        aliases = " ".join(f"p{i}: productConvertId(sourceId: {int(pid)})" for i, pid in enumerate(pos_ids))
        data = (await self._graphql(f"query Convert {{ {aliases} }}", {})).get("data") or {}
        return {pid: data.get(f"p{i}") or -1 for i, pid in enumerate(pos_ids)}

    async def get_products(self, webshop_ids: list[int]) -> dict[int, dict]:
        """Product cards by webshop id; products not sold online are left out."""
        ids = [int(i) for i in webshop_ids if i and i > 0]
        if not ids:
            return {}
        query = "&".join(f"ids={i}" for i in ids)
        rows = await self._request("GET", f"/mobile-services/product/search/v2/products?{query}&sortOn=INPUT_PRODUCT_IDS")
        if isinstance(rows, dict):
            rows = rows.get("products") or []
        return {p["webshopId"]: p for p in rows or [] if p.get("webshopId")}

    async def search_products(self, query: str, size: int = 10) -> dict:
        """Product search by text. (verified)

        GET /mobile-services/product/search/v2?query=..&page=0&size=..&sortOn=RELEVANCE,
        as in appie-go products.go (SearchProductsFiltered). The REST search is the
        one that returns bonusMechanism; sponsored products may be mixed in.
        """
        params = urlencode({"query": query, "page": 0, "size": size, "sortOn": "RELEVANCE"})
        return await self._request("GET", f"/mobile-services/product/search/v2?{params}")

    # list extras

    async def get_total_price(self, products: list[dict[str, int]]) -> dict:
        """Price of products incl. bonus discount: GraphQL FetchTotalPrice. (verified)

        products: [{"id": webshopId, "quantity": n}], as in appie-go's API doc.
        The price to pay is withoutDiscount.amount - discount.amount.
        """
        return await self._graphql(TOTAL_PRICE_QUERY, {"products": products})

    async def get_dont_forget(self, basket: list[dict[str, int]], limit: int = 7) -> dict:
        """The app's "vergeet niet" lane for the list. (verified)

        POST /mobile-services/v2/recommendations/dontforgetlane with the body from
        appie-go's API doc; basket: [{"quantity", "position", "productId"}].
        """
        body = {
            "positiveCmOnly": True,
            "offset": 0,
            "usecaseId": "app_mylist",
            "basketItems": basket,
            "limit": limit,
        }
        return await self._request("POST", "/mobile-services/v2/recommendations/dontforgetlane", body)
