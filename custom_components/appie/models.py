"""Parsing of Albert Heijn API responses.

Kept free of Home Assistant imports so it can be tested on its own.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

ORIGIN_PRODUCT = "PRD"
ORIGIN_TEXT = "TXT"

SOURCE_PERSONAL = "persoonlijk"
SOURCE_PREVIOUS = "eerder_gekocht"
SOURCE_LIST = "op_lijst"
SOURCE_SPOTLIGHT = "spotlight"
SOURCE_CATEGORY = "categorie"


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


@dataclass
class Suggestion:
    """A "vergeet niet" product card."""

    product_id: int
    title: str
    image: str | None = None
    size: str | None = None
    is_bonus: bool = False
    bonus_mechanism: str | None = None
    price: float | None = None
    price_before: float | None = None


def parse_dont_forget(raw: dict) -> list[Suggestion]:
    """Parse the dontforgetlane response (productCards)."""
    suggestions: list[Suggestion] = []
    for card in raw.get("productCards") or []:
        if not card.get("webshopId"):
            continue
        now, before = card.get("currentPrice"), card.get("priceBeforeBonus")
        suggestions.append(
            Suggestion(
                product_id=card["webshopId"],
                title=card.get("title") or "?",
                image=pick_image(card.get("images")),
                size=card.get("salesUnitSize"),
                is_bonus=bool(card.get("isBonus")),
                bonus_mechanism=card.get("bonusMechanism") if card.get("isBonus") else None,
                price=now if now is not None else before,
                price_before=before if now is not None and before != now else None,
            )
        )
    return suggestions


# --- store and koopjes -----------------------------------------------------------

DAY_NAMES = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]


@dataclass
class OpeningDay:
    day: date
    open_from: str | None = None  # "08:00"; None when closed
    open_until: str | None = None

    def window(self, tz: tzinfo | None = None) -> tuple[datetime, datetime] | None:
        """Opening and closing moment; closing at "00:00" means midnight."""
        if not self.open_from or not self.open_until:
            return None
        start = datetime.combine(self.day, _hhmm(self.open_from), tz)
        end = datetime.combine(self.day, _hhmm(self.open_until), tz)
        if end <= start:
            end = datetime.combine(self.day + timedelta(days=1), _hhmm(self.open_until), tz)
        return start, end


def _hhmm(text: str) -> time:
    hours, minutes = (int(part) for part in text.split(":")[:2])
    return time(0, 0) if hours >= 24 else time(hours, minutes)


@dataclass
class Store:
    """The member's favorite AH store (GetFavoriteStore)."""

    id: int
    address: str
    store_type: str | None = None
    opening_days: list[OpeningDay] = field(default_factory=list)
    services: list[str] = field(default_factory=list)

    def today(self, now: datetime) -> OpeningDay | None:
        return next((d for d in self.opening_days if d.day == now.date()), None)

    def is_open(self, now: datetime) -> bool:
        for day in self.opening_days:
            window = day.window(now.tzinfo)
            if window and window[0] <= now < window[1]:
                return True
        return False

    def closing_time(self, now: datetime) -> str | None:
        """Today's closing time while the store is still to open or open today."""
        today = self.today(now)
        window = today.window(now.tzinfo) if today else None
        if window is None or now >= window[1]:
            return None
        return today.open_until

    def upcoming(self, now: datetime) -> list[dict]:
        return [
            {
                "datum": d.day.isoformat(),
                "dag": DAY_NAMES[d.day.weekday()],
                "open": d.open_from,
                "dicht": d.open_until,
            }
            for d in sorted(self.opening_days, key=lambda d: d.day)
            if d.day >= now.date()
        ]


def parse_store(raw: dict) -> Store | None:
    """Parse the GraphQL storesFavouriteStore response; None without a favorite.

    A day without openingHour is taken as closed (appie-go only shows open days).
    """
    store = (raw.get("data") or {}).get("storesFavouriteStore")
    if not store or not store.get("id"):
        return None
    addr = store.get("address") or {}
    street = " ".join(
        str(part) for part in (addr.get("street"), addr.get("houseNumber"), addr.get("houseNumberExtra")) if part
    )
    town = " ".join(str(part) for part in (addr.get("postalCode"), addr.get("city")) if part)
    # AH sends the opening days grouped per week: [[mon..sun], [mon..sun]].
    rows = []
    for row in store.get("openingDays") or []:
        rows.extend(row if isinstance(row, list) else [row])
    days = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            day = date.fromisoformat(row.get("date") or "")
        except ValueError:
            continue
        hours = row.get("openingHour") or {}
        days.append(OpeningDay(day, hours.get("openFrom") or None, hours.get("openUntil") or None))
    return Store(
        id=int(store["id"]),
        address=", ".join(part for part in (street, town) if part),
        store_type=store.get("storeType"),
        opening_days=days,
        services=[s["code"] for s in store.get("services") or [] if s.get("code")],
    )


@dataclass
class Bargain:
    """A last-chance markdown ("koopje") in the store."""

    product_id: int
    title: str
    size: str | None = None
    category: str | None = None
    markdown_type: str | None = None
    expires: str | None = None
    price: float | None = None
    price_was: float | None = None
    percentage: float | None = None

    @property
    def key(self) -> str:
        """One markdown of one product; a new markdown later is a new koopje."""
        return f"{self.product_id}:{self.expires}"


def _money(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def parse_bargains(raw: dict) -> list[Bargain]:
    """Parse the GraphQL bargainItems response (koopjes.go)."""
    bargains: list[Bargain] = []
    for row in (raw.get("data") or {}).get("bargainItems") or []:
        product = row.get("product") or {}
        if not product.get("id"):
            continue
        markdown = row.get("markdown") or {}
        price = row.get("bargainPrice") or {}
        bargains.append(
            Bargain(
                product_id=int(product["id"]),
                title=product.get("title") or "?",
                size=product.get("salesUnitSize"),
                category=row.get("categoryTitle"),
                markdown_type=markdown.get("markdownType"),
                expires=markdown.get("markdownExpirationDate"),
                price=_money(price.get("priceNow")),
                price_was=_money(price.get("priceWas")),
                percentage=markdown.get("markdownPercentage"),
            )
        )
    return bargains


# --- favorite lists -------------------------------------------------------------


@dataclass
class FavoriteList:
    """A favorite list ("lijstje") from FetchFavoriteLists."""

    id: str
    naam: str
    aantal: int
    image: str | None = None


def parse_favorite_lists(raw: dict | None) -> list[FavoriteList]:
    """Parse the GraphQL favoriteListV2 response of FetchFavoriteLists."""
    found = ((raw or {}).get("data") or {}).get("favoriteListV2") or []
    if isinstance(found, dict):
        found = [found]
    return [
        FavoriteList(
            id=row["id"],
            naam=row.get("description") or "?",
            aantal=int(row.get("totalSize") or 0),
            image=row.get("imageUrl") or None,
        )
        for row in found
        if row.get("id")
    ]


def find_favorite_list(lists: list[FavoriteList], wanted: str) -> FavoriteList | None:
    """By id or by name, ignoring case."""
    wanted = wanted.strip().lower()
    return next((fl for fl in lists if fl.id.lower() == wanted or fl.naam.lower() == wanted), None)


def parse_favorite_list_items(raw: dict) -> list[tuple[int, int]]:
    """(product id, quantity) for each product on a favoriteListV2 response."""
    found = (raw.get("data") or {}).get("favoriteListV2") or []
    if isinstance(found, dict):
        found = [found]
    items = (found[0].get("items") or []) if found else []
    return [(int(i["productId"]), max(int(i.get("quantity") or 1), 1)) for i in items if i.get("productId")]


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


def bonus_categories(raw_metadata: dict) -> list[str]:
    """National bonus categories of the current week (metadata tabs, as in bonus.go)."""
    periods = raw_metadata.get("periods") or []
    names: list[str] = []
    for tab in (periods[0].get("tabs") or []) if periods else []:
        for meta in tab.get("urlMetadataList") or []:
            if meta.get("bonusType") == "NATIONAL" and meta.get("description") and meta["description"] not in names:
                names.append(meta["description"])
    return names


@dataclass
class BonusBox:
    """The personal Bonus Box (FetchBonusBoxOffers)."""

    max_activations: int | None
    offers: list[dict]

    @property
    def activated(self) -> int:
        return sum(1 for o in self.offers if o["activated"])


def parse_bonus_box(raw: dict) -> BonusBox:
    data = raw.get("data") or {}
    bundles = data.get("bonusPersonalPromotionBundles") or []
    offers = []
    for promo in data.get("bonusPromotions") or []:
        labels = promo.get("rawPromotionLabels") or []
        price = promo.get("price") or {}
        offers.append(
            {
                "id": promo.get("id"),
                "title": promo.get("title") or "?",
                "category": promo.get("category"),
                "mechanism": labels[0].get("defaultDescription") if labels else None,
                "price": (price.get("now") or {}).get("amount"),
                "price_was": (price.get("was") or {}).get("amount"),
                "image": pick_image(promo.get("images")),
                "hq_id": promo.get("hqId"),
                "activated": promo.get("activationStatus") == "ACTIVATED",
                "start_date": promo.get("periodStart"),
                "end_date": promo.get("periodEnd"),
            }
        )
    return BonusBox(max_activations=bundles[0].get("maximumActivations") if bundles else None, offers=offers)


# 'Field "x" argument "externalId" of type "Int!" is required, but it was not provided.'
# (AH quotes with ", other GraphQL servers with ').
_REQUIRED_ARG = re.compile(r"argument [\"'](\w+)[\"'] of type [\"']([\w!\[\]]+)[\"'] is required")


def required_arguments(messages: list[str]) -> list[tuple[str, str]]:
    """(name, type) of the arguments a GraphQL validation error says are missing."""
    found: list[tuple[str, str]] = []
    for message in messages:
        for name, kind in _REQUIRED_ARG.findall(message or ""):
            if (name, kind) not in found:
                found.append((name, kind))
    return found


def activation_values(args: list[tuple[str, str]], offer: dict) -> dict[str, Any] | None:
    """Fill the activation mutation's arguments from a Bonus Box offer.

    Only names whose meaning is clear are filled; None means an argument was
    asked for that we can't map, so nothing is sent.
    """
    values: dict[str, Any] = {}
    for name, kind in args:
        key = name.lower()
        if key in ("id", "promotionid", "bonuspromotionid", "segmentid", "personalpromotionid"):
            value = offer.get("id")
        elif key in ("hqid", "offerid", "externalid"):
            # AH asks for "externalId: Int!". The schema lists hqId among a Bonus Box
            # offer's external ids (TargetedOfferExternalIds), and hqId is the Int one.
            value = offer.get("hq_id")
        elif key in ("periodstart", "startdate", "validon"):
            value = offer.get("start_date")
        elif key in ("periodend", "enddate"):
            value = offer.get("end_date")
        else:
            return None
        if value is None:
            return None
        values[name] = int(value) if kind.strip("!") == "Int" else str(value)
    return values


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


def receipt_view(receipt: Receipt, detail: ReceiptDetail, tz: tzinfo | None = None) -> dict[str, Any]:
    """One receipt as the picked-receipt sensor and appie.get_receipt show it."""
    return {
        "receipt_id": receipt.id,
        "datetime": receipt.local(tz).isoformat(),
        "total": receipt.total,
        "items": detail.items,
        "discounts": detail.discounts,
        "discount_total": detail.discount_total,
        "payments": detail.payments,
    }


DAY_ABBR = ["ma", "di", "wo", "do", "vr", "za", "zo"]
MONTH_ABBR = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def receipt_label(receipt: Receipt, tz: tzinfo | None = None) -> str:
    """'za 24 okt 2026 14:32 · € 36,16', as shown in the receipt picker."""
    when = receipt.local(tz)
    amount = f"{receipt.total:.2f}".replace(".", ",")
    return (
        f"{DAY_ABBR[when.weekday()]} {when.day} {MONTH_ABBR[when.month - 1]} {when.year} "
        f"{when:%H:%M} · € {amount}"
    )


def monthly_totals(receipts: list[Receipt], today: date, tz: tzinfo | None = None, months: int = 12) -> list[dict]:
    """Spending per calendar month, the last `months` months including this one, oldest first."""
    totals: dict[tuple[int, int], list[float]] = {}
    for receipt in receipts:
        day = receipt.day(tz)
        totals.setdefault((day.year, day.month), []).append(receipt.total)
    result = []
    year, month = today.year, today.month
    for _ in range(months):
        amounts = totals.get((year, month), [])
        result.append(
            {
                "maand": f"{year:04d}-{month:02d}",
                "naam": f"{MONTH_ABBR[month - 1]} {year}",
                "totaal": round(sum(amounts), 2),
                "bonnen": len(amounts),
            }
        )
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return list(reversed(result))


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


def parse_product_detail(raw: dict, nutrition: dict | None = None) -> dict[str, Any] | None:
    """A product detail page (detail/v4) plus FetchProduct nutrition, for appie.get_product."""
    card = raw.get("productCard") or {}
    found = parse_search([card])
    if not found:
        return None
    product = found[0].as_dict()
    nutrients = (((nutrition or {}).get("data") or {}).get("product") or {}).get("tradeItem") or {}
    product.update(
        {
            "brand": card.get("brand"),
            "category": card.get("mainCategory"),
            "subcategory": card.get("subCategory"),
            "nutriscore": card.get("nutriscore"),
            "orderable": card.get("isOrderable"),
            "previously_bought": bool(card.get("isPreviouslyBought")),
            "properties": card.get("propertyIcons") or [],
            "description": re.sub(r"<[^>]+>", " ", card.get("descriptionHighlights") or "").strip() or None,
            "nutrition": [
                {"name": n.get("name"), "value": n.get("value")}
                for block in nutrients.get("nutritions") or []
                for n in block.get("nutrients") or []
            ],
        }
    )
    if product["description"]:
        product["description"] = " ".join(product["description"].split())
    return product


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
