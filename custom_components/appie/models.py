"""Parsing of Albert Heijn API responses.

Kept free of Home Assistant imports so it can be tested on its own.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, tzinfo
from typing import Any

ORIGIN_PRODUCT = "PRD"
ORIGIN_TEXT = "TXT"

SOURCE_PERSONAL = "persoonlijk"
SOURCE_PREVIOUS = "eerder_gekocht"
SOURCE_LIST = "op_lijst"


# --- shopping list -----------------------------------------------------------


@dataclass
class ListItem:
    """One line on the AH shopping list (v2)."""

    key: str
    title: str
    quantity: int
    checked: bool
    origin: str
    product_id: int | None = None
    is_bonus: bool = False
    bonus_mechanism: str | None = None
    image: str | None = None

    def patch(self, *, quantity: int | None = None, checked: bool | None = None) -> dict:
        """Body item for PATCH /shoppinglist/v2/items.

        AH has no per-item id (listItemId is always 0): a PATCH upserts on
        productId for products and on description for free text, and sets
        (not adds) the quantity. quantity 0 removes the item.
        """
        body: dict[str, Any] = {
            "description": self.title,
            "searchTerm": self.title,
            "type": "SHOPPABLE",
            "originCode": self.origin,
            "quantity": self.quantity if quantity is None else quantity,
            "strikeThrough": self.checked if checked is None else checked,
        }
        if self.origin == ORIGIN_PRODUCT and self.product_id is not None:
            body["productId"] = self.product_id
        return body


def new_text_item(text: str) -> ListItem:
    """A free-text item as the app creates it."""
    text = text.strip()
    return ListItem(key=text_key(text), title=text, quantity=1, checked=False, origin=ORIGIN_TEXT)


def new_product_item(product_id: int, title: str = "") -> ListItem:
    """A product-linked item; AH fills in the real title."""
    return ListItem(
        key=f"product:{product_id}",
        title=title or str(product_id),
        quantity=1,
        checked=False,
        origin=ORIGIN_PRODUCT,
        product_id=product_id,
    )


def text_key(text: str) -> str:
    return "text:" + " ".join(text.lower().split())


def parse_list(raw: dict) -> list[ListItem]:
    """Parse GET /shoppinglist/v2/items."""
    items: list[ListItem] = []
    seen: dict[str, int] = {}
    for row in raw.get("items") or []:
        origin = row.get("originCode") or ORIGIN_TEXT
        product = (row.get("productDetails") or {}).get("product") or {}
        product_id = product.get("webshopId") or row.get("productId")
        if origin == ORIGIN_PRODUCT and product_id:
            title = product.get("title") or row.get("description") or f"Product {product_id}"
            key = f"product:{product_id}"
        else:
            vague = row.get("vagueTermDetails") or {}
            title = row.get("description") or vague.get("searchTermValue") or "?"
            key = text_key(title)
            product_id = None
        # The API has no item ids; keep keys unique if the same text is on twice.
        count = seen.get(key, 0)
        seen[key] = count + 1
        if count:
            key = f"{key}#{count + 1}"
        items.append(
            ListItem(
                key=key,
                title=title,
                quantity=max(int(row.get("quantity") or 1), 1),
                checked=bool(row.get("strikedthrough")),
                origin=origin if product_id else ORIGIN_TEXT,
                product_id=product_id,
                is_bonus=bool(product.get("isBonus") or (row.get("vagueTermDetails") or {}).get("bonus")),
                bonus_mechanism=product.get("bonusMechanism"),
                image=pick_image(product.get("images")),
            )
        )
    return items


def open_products(items: list[ListItem]) -> list[ListItem]:
    """Product items still to buy (free text has no price or product id)."""
    return [i for i in items if i.product_id and not i.checked]


def list_signature(items: list[ListItem]) -> tuple[tuple[int, int], ...]:
    """What the price and the suggestions depend on: open products and quantities."""
    return tuple(sorted((i.product_id, i.quantity) for i in open_products(items)))


@dataclass
class ListCost:
    """What the open products on the list cost (FetchTotalPrice)."""

    without_discount: float
    discount: float
    products: int
    free_text: int

    @property
    def total(self) -> float:
        return round(self.without_discount - self.discount, 2)


def count_free_text(items: list[ListItem]) -> int:
    return sum(1 for i in items if not i.product_id and not i.checked)


def parse_total_price(raw: dict, items: list[ListItem]) -> ListCost:
    """Parse the GraphQL totalPrice response."""
    price = (raw.get("data") or {}).get("totalPrice") or {}
    return ListCost(
        without_discount=round(float((price.get("withoutDiscount") or {}).get("amount") or 0), 2),
        discount=round(float((price.get("discount") or {}).get("amount") or 0), 2),
        products=len(open_products(items)),
        free_text=count_free_text(items),
    )


# --- bonus -------------------------------------------------------------------


@dataclass
class BonusOffer:
    """A bonus offer, either a single product or a group ("Alle ...")."""

    key: str
    title: str
    mechanism: str
    source: str
    price: float | None = None
    price_was: float | None = None
    image: str | None = None
    end_date: str | None = None
    activated: bool | None = None
    on_list: bool = False
    product_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = asdict(self)
        data.pop("product_ids")
        return data


def pick_image(images: list[dict] | None, min_width: int = 200) -> str | None:
    """Smallest rendition that is still at least min_width wide."""
    if not images:
        return None
    usable = [i for i in images if i.get("url")]
    if not usable:
        return None
    big_enough = [i for i in usable if (i.get("width") or 0) >= min_width]
    pool = big_enough or usable
    return min(pool, key=lambda i: i.get("width") or 0)["url"]


def parse_bonus_section(raw: dict, source: str) -> list[BonusOffer]:
    """Parse a bonuspage section (personal or previously-bought)."""
    offers: list[BonusOffer] = []
    for entry in raw.get("bonusGroupOrProducts") or []:
        if product := entry.get("product"):
            pid = product.get("webshopId")
            offers.append(
                BonusOffer(
                    key=f"product:{pid}",
                    title=product.get("title") or "?",
                    mechanism=product.get("bonusMechanism") or "Bonus",
                    source=source,
                    price=product.get("currentPrice"),
                    price_was=product.get("priceBeforeBonus"),
                    image=pick_image(product.get("images")),
                    end_date=product.get("bonusEndDate"),
                    activated=_activated(product.get("activationStatus")),
                    product_ids=[pid] if pid else [],
                )
            )
        elif group := entry.get("bonusGroup"):
            offers.append(
                BonusOffer(
                    key=f"group:{group.get('segmentId') or group.get('id')}",
                    title=group.get("segmentDescription") or "?",
                    mechanism=group.get("discountDescription") or "Bonus",
                    source=source,
                    price=group.get("exampleForPrice"),
                    price_was=group.get("exampleFromPrice"),
                    image=pick_image(group.get("images")),
                    end_date=group.get("bonusEndDate"),
                    activated=_activated(group.get("activationStatus")),
                    product_ids=[
                        p["webshopId"] for p in group.get("products") or [] if p.get("webshopId")
                    ],
                )
            )
    return offers


def _activated(status: str | None) -> bool | None:
    if not status:
        return None
    return status == "ACTIVATED"


def relevant_bonus(
    personal: list[BonusOffer],
    previous: list[BonusOffer],
    list_items: list[ListItem],
) -> list[BonusOffer]:
    """Merge the bonus that matters to us, most relevant first.

    Order: on the shopping list, then personal bonus, then previously bought.
    Products on the list that are on bonus but in neither section are added
    from the list itself.
    """
    on_list_ids = {i.product_id for i in list_items if i.product_id and not i.checked}
    merged: dict[str, BonusOffer] = {}
    for offer in [*personal, *previous]:
        if offer.key in merged:
            continue
        merged[offer.key] = replace(offer, on_list=bool(on_list_ids.intersection(offer.product_ids)))
    covered = {pid for o in merged.values() for pid in o.product_ids}
    for item in list_items:
        if item.checked or not item.is_bonus or not item.product_id or item.product_id in covered:
            continue
        merged[item.key] = BonusOffer(
            key=item.key,
            title=item.title,
            mechanism=item.bonus_mechanism or "Bonus",
            source=SOURCE_LIST,
            image=item.image,
            on_list=True,
            product_ids=[item.product_id],
        )
    rank = {SOURCE_LIST: 1, SOURCE_PERSONAL: 1, SOURCE_PREVIOUS: 2}
    return sorted(merged.values(), key=lambda o: (not o.on_list, rank[o.source]))


def bonus_period(raw_metadata: dict) -> tuple[str | None, str | None]:
    """Current bonus week (start, end) from bonuspage/v3/metadata."""
    periods = raw_metadata.get("periods") or []
    if not periods:
        return None, None
    return periods[0].get("bonusStartDate"), periods[0].get("bonusEndDate")


# --- receipts ----------------------------------------------------------------


@dataclass
class Receipt:
    id: str
    when: str  # ISO timestamp in UTC ("...Z")
    total: float

    def local(self, tz: tzinfo | None = None) -> datetime:
        moment = datetime.fromisoformat(self.when)
        return moment.astimezone(tz) if moment.tzinfo else moment

    def day(self, tz: tzinfo | None = None) -> date:
        return self.local(tz).date()


@dataclass
class ReceiptDetail:
    id: str
    items: list[dict]
    discounts: list[dict]
    discount_total: float
    payments: list[str]


def parse_receipts(raw: dict) -> list[Receipt]:
    """Parse the GraphQL posReceiptsPage response, newest first."""
    rows = ((raw.get("data") or {}).get("posReceiptsPage") or {}).get("posReceipts") or []
    receipts = [
        Receipt(id=r["id"], when=r["dateTime"], total=float((r.get("totalAmount") or {}).get("amount") or 0))
        for r in rows
        if r.get("id") and r.get("dateTime")
    ]
    return sorted(receipts, key=lambda r: r.when, reverse=True)


def parse_receipt_detail(raw: dict) -> ReceiptDetail:
    """Parse the GraphQL posReceiptDetails response."""
    det = (raw.get("data") or {}).get("posReceiptDetails") or {}
    items = [
        {
            "name": pos_name(p.get("name") or ""),
            "quantity": p.get("quantity") or 1,
            "amount": (p.get("amount") or {}).get("amount"),
        }
        for p in det.get("products") or []
    ]
    discounts = [
        {"name": d.get("name") or "", "amount": (d.get("amount") or {}).get("amount") or 0}
        for d in det.get("discounts") or []
    ]
    return ReceiptDetail(
        id=det.get("id") or "",
        items=items,
        discounts=discounts,
        discount_total=round(sum(d["amount"] for d in discounts), 2),
        payments=[p.get("method") or "" for p in det.get("payments") or []],
    )


def pos_name(name: str) -> str:
    """Till names are shouty abbreviations ("BIO BANAAN"); soften them."""
    name = " ".join(name.split())
    if not name.isupper():
        return name
    soft = name[:1] + name[1:].lower()
    # Keep the store brand recognisable: "AH ELSTAR" -> "AH elstar".
    return "AH" + soft[2:] if name.startswith("AH ") else soft


def month_total(receipts: list[Receipt], today: date, tz: tzinfo | None = None) -> float:
    return round(
        sum(r.total for r in receipts if (r.day(tz).year, r.day(tz).month) == (today.year, today.month)), 2
    )


# --- most bought ---------------------------------------------------------------

# Till lines that are not groceries.
NOT_A_PRODUCT = re.compile(r"STATIEGELD|EMBALLAGE|\bTAS\b|TASJE|ZEGEL|SPAAR|AIRMILES", re.I)


@dataclass
class Favorite:
    """A product we buy often, ready to put on the list."""

    rank: int
    title: str
    times: int
    product_id: int | None = None
    image: str | None = None
    is_bonus: bool = False
    bonus_mechanism: str | None = None

    def as_list_item(self) -> ListItem:
        if self.product_id:
            return new_product_item(self.product_id, self.title)
        return new_text_item(self.title)


def receipt_lines(raw: dict) -> list[list]:
    """[[pos_id, name, quantity, amount], ...] from a posReceiptDetails response."""
    det = (raw.get("data") or {}).get("posReceiptDetails") or {}
    return [
        [p.get("id"), p.get("name") or "", p.get("quantity") or 1, (p.get("amount") or {}).get("amount") or 0]
        for p in det.get("products") or []
        if p.get("id")
    ]


def rank_purchases(receipts: list[list[list]]) -> list[tuple[int, str, int]]:
    """Rank till products by on how many receipts they appear (then quantity).

    receipts: one receipt_lines() list per receipt. Returns (pos_id, name, times).
    """
    times: dict[int, int] = {}
    qty: dict[int, float] = {}
    names: dict[int, str] = {}
    for lines in receipts:
        seen = set()
        for pos_id, name, quantity, amount in lines:
            if amount <= 0 or NOT_A_PRODUCT.search(name):
                continue
            names[pos_id] = name
            qty[pos_id] = qty.get(pos_id, 0) + quantity
            if pos_id not in seen:
                times[pos_id] = times.get(pos_id, 0) + 1
                seen.add(pos_id)
    order = sorted(times, key=lambda i: (-times[i], -qty[i], names[i]))
    return [(i, names[i], times[i]) for i in order]


def build_favorites(
    ranked: list[tuple[int, str, int]],
    webshop_ids: dict[int, int],
    products: dict[int, dict],
    limit: int = 10,
) -> list[Favorite]:
    """Top products: webshop product when AH sells it online, else the till name."""
    favorites: list[Favorite] = []
    seen: set = set()
    for pos_id, name, times in ranked:
        wid = webshop_ids.get(pos_id)
        product = products.get(wid) if wid and wid > 0 else None
        key = wid if product else pos_name(name).lower()
        if key in seen:
            continue
        seen.add(key)
        if product:
            favorites.append(
                Favorite(
                    rank=len(favorites) + 1,
                    title=product.get("title") or pos_name(name),
                    times=times,
                    product_id=wid,
                    image=pick_image(product.get("images")),
                    is_bonus=bool(product.get("isBonus")),
                    bonus_mechanism=product.get("bonusMechanism"),
                )
            )
        else:
            favorites.append(Favorite(rank=len(favorites) + 1, title=pos_name(name), times=times))
        if len(favorites) == limit:
            break
    return favorites


def favorite_attributes(favorite: Favorite, list_items: list[ListItem]) -> dict[str, Any]:
    """The attributes a "vaak gekocht" button shows, matched against the list."""
    on_list = next((i for i in list_items if i.key == favorite.as_list_item().key), None)
    return {
        "rank": favorite.rank,
        "title": favorite.title,
        "times_bought": favorite.times,
        "product_id": favorite.product_id,
        "bonus": favorite.bonus_mechanism if favorite.is_bonus else None,
        "on_list": on_list is not None and not on_list.checked,
        "quantity_on_list": on_list.quantity if on_list and not on_list.checked else 0,
    }


# --- product search ------------------------------------------------------------


@dataclass
class SearchResult:
    """A product from the REST search, in the shape the services return."""

    product_id: int
    title: str
    size: str | None = None
    price: float | None = None
    image: str | None = None
    is_bonus: bool = False
    bonus_mechanism: str | None = None
    previously_bought: bool = False

    def as_dict(self) -> dict:
        data = asdict(self)
        data.pop("previously_bought")
        return data


def parse_search(raw: dict | list | None) -> list[SearchResult]:
    """Parse GET /product/search/v2 (or a bare product list)."""
    rows = raw.get("products") if isinstance(raw, dict) else raw
    results: list[SearchResult] = []
    for p in rows or []:
        if not p.get("webshopId"):
            continue
        results.append(
            SearchResult(
                product_id=p["webshopId"],
                title=p.get("title") or "?",
                size=p.get("salesUnitSize"),
                price=p.get("currentPrice") or p.get("priceBeforeBonus"),
                image=pick_image(p.get("images")),
                is_bonus=bool(p.get("isBonus")),
                bonus_mechanism=p.get("bonusMechanism") if p.get("isBonus") else None,
                previously_bought=bool(p.get("isPreviouslyBought")),
            )
        )
    return results


MATCH_FAVORITE = "vaak_gekocht"
MATCH_PREVIOUS = "eerder_gekocht"
MATCH_SEARCH = "beste_zoekresultaat"


def best_match(results: list[SearchResult], favorites: list[Favorite]) -> tuple[SearchResult, str] | None:
    """Pick what to put on the list for a search term.

    Prefer the most bought product among the results, then something bought
    before, then simply the most relevant result.
    """
    if not results:
        return None
    rank = {f.product_id: f.rank for f in favorites if f.product_id}
    favorite = min((r for r in results if r.product_id in rank), key=lambda r: rank[r.product_id], default=None)
    if favorite:
        return favorite, MATCH_FAVORITE
    previous = next((r for r in results if r.previously_bought), None)
    if previous:
        return previous, MATCH_PREVIOUS
    return results[0], MATCH_SEARCH
