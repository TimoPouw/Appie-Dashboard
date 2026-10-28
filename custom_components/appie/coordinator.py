"""Data update coordinators for the Albert Heijn integration."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AppieAuthError, AppieClient, AppieError
from .const import (
    BARGAINS_INTERVAL,
    BONUS_INTERVAL,
    DONT_FORGET_COOLDOWN,
    DONT_FORGET_INTERVAL,
    CONF_FAVORITES_COUNT,
    CONF_FAVORITES_DAYS,
    DOMAIN,
    EVENT_BARGAIN_FAVORITE,
    FAVORITES_COUNT,
    FAVORITES_DAYS,
    FAVORITE_LISTS_INTERVAL,
    FAVORITES_INTERVAL,
    LIST_COST_COOLDOWN,
    LIST_COST_INTERVAL,
    LIST_INTERVAL,
    RECEIPTS_INTERVAL,
    RECEIPTS_PAGE_SIZE,
    SAVINGS_INTERVAL,
    STORE_INTERVAL,
)
from .models import (
    SOURCE_PERSONAL,
    SOURCE_PREVIOUS,
    SOURCE_SPOTLIGHT,
    Bargain,
    BonusBox,
    BonusOffer,
    Favorite,
    FavoriteList,
    ListCost,
    ListItem,
    Receipt,
    ReceiptDetail,
    Store as AhStore,
    Suggestion,
    bonus_period,
    build_favorites,
    count_free_text,
    list_signature,
    open_products,
    parse_total_price,
    month_total,
    monthly_totals,
    parse_bargains,
    parse_bonus_box,
    parse_bonus_section,
    parse_dont_forget,
    parse_favorite_lists,
    parse_list,
    parse_receipt_detail,
    parse_receipts,
    parse_store,
    rank_purchases,
    receipt_lines,
    relevant_bonus,
    add_program_balances,
    current_programs,
    parse_challenges,
    parse_gift_cards,
    parse_miles,
    parse_premium,
    parse_purchase_stamps,
)

_LOGGER = logging.getLogger(__name__)

# Receipts are paged; stop after this many pages even if the month is longer.
MAX_RECEIPT_PAGES = 4
# Spending per month over this many months; older months are fetched once a day.
HISTORY_MONTHS = 12
MAX_HISTORY_PAGES = 24


@dataclass
class AppieData:
    """Runtime data stored on the config entry."""

    client: AppieClient
    shopping_list: ListCoordinator
    bonus: BonusCoordinator
    receipts: ReceiptsCoordinator
    favorites: FavoritesCoordinator
    list_cost: ListCostCoordinator
    dont_forget: DontForgetCoordinator
    store: StoreCoordinator
    bargains: BargainsCoordinator
    receipt_viewer: ReceiptViewerCoordinator
    spotlight: SpotlightCoordinator
    bonus_box: BonusBoxCoordinator
    favorite_lists: FavoriteListsCoordinator
    savings: SavingsCoordinator


type AppieConfigEntry = ConfigEntry[AppieData]


class _AppieCoordinator[T](DataUpdateCoordinator[T]):
    """Shared error handling."""

    def __init__(
        self, hass: HomeAssistant, entry: AppieConfigEntry, client: AppieClient, name: str, interval, **kwargs
    ) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {name}", update_interval=interval, **kwargs
        )
        self.client = client

    async def _async_update_data(self) -> T:
        try:
            return await self._fetch()
        except AppieAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AppieError as err:
            raise UpdateFailed(str(err)) from err

    async def _fetch(self) -> T:
        raise NotImplementedError


class ListCoordinator(_AppieCoordinator[list[ListItem]]):
    """The shopping list, polled every minute for two-way sync."""

    def __init__(self, hass, entry, client) -> None:
        super().__init__(hass, entry, client, "boodschappenlijst", LIST_INTERVAL)

    async def _fetch(self) -> list[ListItem]:
        return parse_list(await self.client.get_list() or {})


@dataclass
class BonusData:
    offers: list[BonusOffer]
    period_start: str | None
    period_end: str | None


class BonusCoordinator(_AppieCoordinator[BonusData]):
    """Bonus relevant to us; matched against the list on every list update."""

    def __init__(self, hass, entry, client, shopping_list: ListCoordinator) -> None:
        super().__init__(hass, entry, client, "bonus", BONUS_INTERVAL)
        self._list = shopping_list
        self._personal: list[BonusOffer] = []
        self._previous: list[BonusOffer] = []
        self._period: tuple[str | None, str | None] = (None, None)

    async def _fetch(self) -> BonusData:
        today = dt_util.now().date()
        start, end = bonus_period(await self.client.get_bonus_metadata() or {})
        start = start or today.isoformat()
        self._period = (start, end)
        self._personal = parse_bonus_section(await self.client.get_personal_bonus(start) or {}, SOURCE_PERSONAL)
        self._previous = parse_bonus_section(
            await self.client.get_previously_bought_bonus(today) or {}, SOURCE_PREVIOUS
        )
        return self._merge()

    def _merge(self) -> BonusData:
        return BonusData(
            offers=relevant_bonus(list(self._personal), list(self._previous), self._list.data or []),
            period_start=self._period[0],
            period_end=self._period[1],
        )

    def list_changed(self) -> None:
        """Re-match against the list without calling AH again."""
        if self.data is None:
            return
        # A new bonus week starts on Monday; fetch fresh offers once it has.
        end = self._period[1]
        if end and dt_util.now().date() > date.fromisoformat(end):
            self.hass.async_create_task(self.async_request_refresh())
            return
        # Not async_set_updated_data: that restarts the 6 h timer, and the list
        # updates every minute, so the bonus would never be fetched again.
        self.data = self._merge()
        self.async_update_listeners()


@dataclass
class ReceiptsData:
    receipts: list[Receipt]
    latest: Receipt | None
    latest_detail: ReceiptDetail | None
    month_total: float
    month_count: int
    per_month: list[dict] = field(default_factory=list)


class ReceiptsCoordinator(_AppieCoordinator[ReceiptsData]):
    """In-store receipts (kassabonnen)."""

    def __init__(self, hass, entry, client) -> None:
        super().__init__(hass, entry, client, "kassabonnen", RECEIPTS_INTERVAL)
        self._details: dict[str, ReceiptDetail] = {}
        # Receipts of earlier months: they don't change, so fetched once a day.
        self._history: list[Receipt] = []
        self._history_day: date | None = None

    async def _fetch(self) -> ReceiptsData:
        tz = dt_util.get_default_time_zone()
        today = dt_util.now().date()
        month_start = today.replace(day=1)
        need_history = self._history_day != today
        oldest = month_start
        if need_history:
            for _ in range(HISTORY_MONTHS - 1):
                oldest = (oldest - timedelta(days=1)).replace(day=1)
        fetched: list[Receipt] = []
        for page in range(MAX_HISTORY_PAGES if need_history else MAX_RECEIPT_PAGES):
            batch = parse_receipts(await self.client.get_receipts(page * RECEIPTS_PAGE_SIZE, RECEIPTS_PAGE_SIZE))
            fetched.extend(batch)
            if len(batch) < RECEIPTS_PAGE_SIZE or batch[-1].day(tz) < oldest:
                break
        fetched.sort(key=lambda r: r.when, reverse=True)
        if need_history:
            self._history = [r for r in fetched if r.day(tz) < month_start]
            self._history_day = today
        # The picker gets what a normal fetch returns (this month, at least a page), not the year.
        in_month = sum(1 for r in fetched if r.day(tz) >= month_start)
        receipts = fetched[: max(in_month, RECEIPTS_PAGE_SIZE)]
        known = {r.id for r in fetched}
        year = fetched + [r for r in self._history if r.id not in known]
        latest = receipts[0] if receipts else None
        if latest and latest.id not in self._details:
            self._details = {latest.id: parse_receipt_detail(await self.client.get_receipt_detail(latest.id))}
        this_month = [r for r in receipts if r.day(tz) >= month_start]
        return ReceiptsData(
            receipts=receipts,
            latest=latest,
            latest_detail=self._details.get(latest.id) if latest else None,
            month_total=month_total(receipts, today, tz),
            month_count=len(this_month),
            per_month=monthly_totals(year, today, tz, HISTORY_MONTHS),
        )


class FavoritesCoordinator(_AppieCoordinator[list[Favorite]]):
    """What we buy most, counted over the receipts of the last months.

    Receipt lines never change, so they are kept in HA storage and each
    receipt is fetched only once.
    """

    STORAGE_VERSION = 1
    # Fetch at most this many new receipts per update (the first run catches up).
    MAX_NEW_RECEIPTS = 120

    def __init__(self, hass, entry, client) -> None:
        super().__init__(hass, entry, client, "vaak gekocht", FAVORITES_INTERVAL)
        self._store: Store[dict] = Store(hass, self.STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.receipt_lines")
        self._lines: dict[str, list] | None = None
        self.count: int = entry.options.get(CONF_FAVORITES_COUNT, FAVORITES_COUNT)
        self.days: int = entry.options.get(CONF_FAVORITES_DAYS, FAVORITES_DAYS)

    async def _fetch(self) -> list[Favorite]:
        if self._lines is None:
            self._lines = ((await self._store.async_load()) or {}).get("lines", {})
        tz = dt_util.get_default_time_zone()
        since = dt_util.now().date() - timedelta(days=self.days)
        receipts: list[Receipt] = []
        # Roughly a page of 50 receipts per month, more for a long window.
        for page in range(max(MAX_RECEIPT_PAGES, self.days // 30 + 1)):
            batch = parse_receipts(await self.client.get_receipts(page * RECEIPTS_PAGE_SIZE, RECEIPTS_PAGE_SIZE))
            receipts.extend(batch)
            if len(batch) < RECEIPTS_PAGE_SIZE or batch[-1].day(tz) < since:
                break
        recent = [r for r in receipts if r.day(tz) >= since]
        missing = [r.id for r in recent if r.id not in self._lines][: self.MAX_NEW_RECEIPTS]
        for receipt_id in missing:
            self._lines[receipt_id] = receipt_lines(await self.client.get_receipt_detail(receipt_id))
        keep = {r.id for r in recent}
        self._lines = {k: v for k, v in self._lines.items() if k in keep}
        if missing:
            await self._store.async_save({"lines": self._lines})

        ranked = rank_purchases([self._lines[r.id] for r in recent if r.id in self._lines])
        # Twice as many candidates: some till lines map to the same product.
        candidates = ranked[: 2 * self.count]
        webshop_ids = await self.client.convert_pos_ids([pos_id for pos_id, _, _ in candidates])
        products = await self.client.get_products(list(webshop_ids.values()))
        return build_favorites(candidates, webshop_ids, products, self.count)


class _ListDrivenCoordinator[T](_AppieCoordinator[T]):
    """Data that depends on the products on the list.

    The list is polled every minute; only a change in the open products or
    their quantities triggers a new call, and the debouncer folds a burst of
    edits into one.
    """

    def __init__(
        self, hass, entry, client, shopping_list: ListCoordinator, name: str, interval, cooldown: float, immediate: bool
    ) -> None:
        super().__init__(
            hass,
            entry,
            client,
            name,
            interval,
            request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=cooldown, immediate=immediate),
        )
        self._list = shopping_list
        self._signature: tuple | None = None

    async def _fetch(self) -> T:
        items = list(self._list.data or [])
        # Set before the call: a failing call is retried on the interval, not every minute.
        self._signature = list_signature(items)
        return await self._fetch_for(items)

    async def _fetch_for(self, items: list[ListItem]) -> T:
        raise NotImplementedError

    def list_changed(self) -> None:
        if list_signature(self._list.data or []) != self._signature:
            self.hass.async_create_task(self.async_request_refresh())
        elif self.data is not None:
            self._local_update(self._list.data or [])

    def _local_update(self, items: list[ListItem]) -> None:
        """React to list changes that need no call (free text, ticked items)."""


class ListCostCoordinator(_ListDrivenCoordinator[ListCost]):
    """What the products on the list cost, after bonus (FetchTotalPrice)."""

    def __init__(self, hass, entry, client, shopping_list: ListCoordinator) -> None:
        super().__init__(
            hass, entry, client, shopping_list, "lijst kosten", LIST_COST_INTERVAL, LIST_COST_COOLDOWN, True
        )

    async def _fetch_for(self, items: list[ListItem]) -> ListCost:
        products = [{"id": i.product_id, "quantity": i.quantity} for i in open_products(items)]
        if not products:
            return ListCost(0.0, 0.0, 0, count_free_text(items))
        return parse_total_price(await self.client.get_total_price(products) or {}, items)

    def _local_update(self, items: list[ListItem]) -> None:
        free_text = count_free_text(items)
        if free_text != self.data.free_text:
            # Not async_set_updated_data: that would restart the 6 h timer.
            self.data = replace(self.data, free_text=free_text)
            self.async_update_listeners()


class DontForgetCoordinator(_ListDrivenCoordinator[list[Suggestion]]):
    """The app's "vergeet niet" suggestions for what is on the list."""

    def __init__(self, hass, entry, client, shopping_list: ListCoordinator) -> None:
        # immediate: the first change is fetched right away, then at most once per cooldown.
        super().__init__(
            hass, entry, client, shopping_list, "vergeet niet", DONT_FORGET_INTERVAL, DONT_FORGET_COOLDOWN, True
        )

    async def _fetch_for(self, items: list[ListItem]) -> list[Suggestion]:
        basket = [
            {"quantity": i.quantity, "position": n, "productId": i.product_id}
            for n, i in enumerate(open_products(items), start=1)
        ]
        if not basket:
            # Not documented what the lane returns for an empty basket; don't ask.
            return []
        on_list = {i.product_id for i in items if i.product_id}
        return [s for s in parse_dont_forget(await self.client.get_dont_forget(basket) or {})
                if s.product_id not in on_list]


class StoreCoordinator(_AppieCoordinator[AhStore | None]):
    """The favorite store with its opening hours; None if none is set."""

    def __init__(self, hass, entry, client) -> None:
        super().__init__(hass, entry, client, "winkel", STORE_INTERVAL)

    async def _fetch(self) -> AhStore | None:
        return parse_store(await self.client.get_favorite_store() or {})


class BargainsCoordinator(_AppieCoordinator[list[Bargain]]):
    """Koopjes in the favorite store, polled only while it is open.

    Fires appie_koopje_favoriet once per koopje of a product from "vaak
    gekocht"; which ones fired is kept in storage so a restart doesn't repeat.
    """

    STORAGE_VERSION = 1

    def __init__(self, hass, entry, client, store: StoreCoordinator, favorites: FavoritesCoordinator) -> None:
        super().__init__(hass, entry, client, "koopjes", BARGAINS_INTERVAL)
        self._store_coordinator = store
        self.favorites = favorites
        self._fired_store: Store[dict] = Store(hass, self.STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.koopjes")
        self._fired: set[str] | None = None

    def favorite_ids(self) -> set[int]:
        # Assumes bargainItems' product.id is the webshop id, as Product.id is in
        # the other GraphQL queries; appie-go does not say so explicitly.
        return {f.product_id for f in self.favorites.data or [] if f.product_id}

    async def _fetch(self) -> list[Bargain]:
        store = self._store_coordinator.data
        if store is None:
            return []
        if not store.is_open(dt_util.now()) and self.data is not None:
            # Closed: nothing changes on the shelves, keep what we had.
            return self.data
        bargains = parse_bargains(await self.client.get_bargains(store.id) or {})
        await self._announce(bargains)
        return bargains

    def favorites_changed(self) -> None:
        """The ranking changed (or arrived after startup): check the koopjes we have."""
        if self.data:
            self.hass.async_create_task(self._announce(self.data))

    async def _announce(self, bargains: list[Bargain]) -> None:
        if self._fired is None:
            self._fired = set(((await self._fired_store.async_load()) or {}).get("fired", []))
        favorites = self.favorite_ids()
        store = self._store_coordinator.data
        new = [b for b in bargains if b.product_id in favorites and b.key not in self._fired]
        for bargain in new:
            self.hass.bus.async_fire(
                EVENT_BARGAIN_FAVORITE,
                {
                    "product_id": bargain.product_id,
                    "title": bargain.title,
                    "size": bargain.size,
                    "category": bargain.category,
                    "markdown_type": bargain.markdown_type,
                    "expires": bargain.expires,
                    "price": bargain.price,
                    "price_was": bargain.price_was,
                    "store_id": store.id if store else None,
                },
            )
            self._fired.add(bargain.key)
        # Forget markdowns that have expired; keeps the stored set small.
        today = dt_util.now().date().isoformat()
        expired = {k for k in self._fired if k.split(":", 1)[1] not in ("None", "") and k.split(":", 1)[1] < today}
        if new or expired:
            self._fired -= expired
            await self._fired_store.async_save({"fired": sorted(self._fired)})


class SpotlightCoordinator(_AppieCoordinator[list[BonusOffer]]):
    """The week's highlighted bonus (spotlight section)."""

    def __init__(self, hass, entry, client) -> None:
        super().__init__(hass, entry, client, "bonus spotlight", BONUS_INTERVAL)

    async def _fetch(self) -> list[BonusOffer]:
        raw = await self.client.get_spotlight_bonus(dt_util.now().date())
        return parse_bonus_section(raw or {}, SOURCE_SPOTLIGHT)


class BonusBoxCoordinator(_AppieCoordinator[BonusBox | None]):
    """The personal Bonus Box, for the bonus week the bonus coordinator knows."""

    def __init__(self, hass, entry, client, bonus: BonusCoordinator) -> None:
        super().__init__(hass, entry, client, "bonus box", BONUS_INTERVAL)
        self._bonus = bonus

    async def _fetch(self) -> BonusBox | None:
        period = self._bonus.data
        if period is None or not period.period_start or not period.period_end:
            return None
        return parse_bonus_box(await self.client.get_bonus_box(period.period_start, period.period_end) or {})


class FavoriteListsCoordinator(_AppieCoordinator[list[FavoriteList]]):
    """The favorite lists ("lijstjes") with their size."""

    def __init__(self, hass, entry, client) -> None:
        super().__init__(hass, entry, client, "favoriete lijsten", FAVORITE_LISTS_INTERVAL)

    async def _fetch(self) -> list[FavoriteList]:
        return parse_favorite_lists(await self.client.get_favorite_lists())


@dataclass
class ViewedReceipt:
    receipt: Receipt
    detail: ReceiptDetail


class ReceiptViewerCoordinator(_AppieCoordinator[ViewedReceipt | None]):
    """The receipt picked in the select entity, fetched when picked.

    Only the picked receipt is held, in memory; nothing is stored. It starts
    on the latest receipt, whose details the receipts coordinator already has.
    """

    def __init__(self, hass, entry, client, receipts: ReceiptsCoordinator) -> None:
        super().__init__(hass, entry, client, "kassabon bekijken", None)
        self.receipts = receipts
        self.selected: str | None = None
        # Signs the PDF links; new on every start, never stored.
        self.pdf_token = secrets.token_urlsafe(32)

    def pdf_url(self, receipt_id: str) -> str:
        return f"/api/{DOMAIN}/kassabon/{receipt_id}?token={self.pdf_token}"

    def receipts_changed(self) -> None:
        """A new receipt came in: follow it unless another one was picked."""
        if self.selected is None and self.receipts.data and self.receipts.data.latest:
            if not self.data or self.data.receipt.id != self.receipts.data.latest.id:
                self.hass.async_create_task(self.async_refresh())

    def find(self, receipt_id: str) -> Receipt | None:
        data = self.receipts.data
        return next((r for r in data.receipts if r.id == receipt_id), None) if data else None

    async def _fetch(self) -> ViewedReceipt | None:
        data = self.receipts.data
        receipt_id = self.selected or (data.latest.id if data and data.latest else None)
        receipt = self.find(receipt_id) if receipt_id else None
        if receipt is None:
            return None
        if self.data and self.data.receipt.id == receipt.id:
            return self.data
        if data.latest_detail and data.latest_detail.id == receipt.id:
            return ViewedReceipt(receipt, data.latest_detail)
        return ViewedReceipt(receipt, parse_receipt_detail(await self.client.get_receipt_detail(receipt.id)))

    async def async_select(self, receipt_id: str) -> None:
        self.selected = receipt_id
        await self.async_refresh()


@dataclass
class Savings:
    """What you save at AH; a part is None when AH doesn't (yet) give it."""

    stamps: dict | None = None
    miles: dict | None = None
    programs: list[dict] | None = None
    challenges: list[dict] | None = None
    premium: dict | None = None
    gift_cards: list[dict] | None = None


class SavingsCoordinator(_AppieCoordinator[Savings]):
    """Koopzegels, Air Miles, spaaracties, challenges, Premium and credit.

    Each part is its own request: one that fails keeps its last value and
    leaves the others alone.
    """

    def __init__(self, hass, entry, client, receipts: ReceiptsCoordinator) -> None:
        super().__init__(hass, entry, client, "sparen", SAVINGS_INTERVAL)
        self._receipts = receipts
        self._latest_receipt: str | None = None

    async def _part(self, name: str, fetch):
        try:
            return True, await fetch()
        except AppieAuthError:
            raise
        except AppieError as err:
            _LOGGER.debug("%s not available: %s", name, err)
            return False, None

    async def _fetch(self) -> Savings:
        old = self.data or Savings()
        new = replace(old)
        ok, raw = await self._part("koopzegels", self.client.get_purchase_stamps)
        if ok:
            new.stamps = parse_purchase_stamps(raw)
        ok, raw = await self._part("air miles", self.client.get_miles)
        if ok:
            new.miles = parse_miles(raw)
        ok, raw = await self._part("spaaracties", self.client.get_loyalty)
        if ok:
            programs = current_programs(raw.get("loyaltyPrograms"), dt_util.now().date())
            if programs:
                ids = [p["id"] for p in programs]
                ok_points, points = await self._part("spaarpunten", lambda: self.client.get_loyalty_balances(ids))
                if ok_points:
                    programs = add_program_balances(programs, points)
            new.programs = programs if raw.get("loyaltyPrograms") is not None else old.programs
            new.challenges = (
                parse_challenges(raw.get("loyaltyChallenges"), dt_util.now().date())
                if raw.get("loyaltyChallenges") is not None
                else old.challenges
            )
        ok, raw = await self._part("premium", self.client.get_premium)
        if ok:
            new.premium = parse_premium(raw)
        ok, raw = await self._part("cadeaukaarten", self.client.get_wallet)
        if ok:
            if raw.get("paymentsGetGiftCards") is not None:
                new.gift_cards = parse_gift_cards(raw["paymentsGetGiftCards"])
        return new

    def receipts_changed(self) -> None:
        """A new receipt means new koopzegels or points: fetch again."""
        latest = self._receipts.data.latest if self._receipts.data else None
        latest_id = latest.id if latest else None
        if self._latest_receipt is not None and latest_id != self._latest_receipt:
            self.hass.async_create_task(self.async_request_refresh())
        self._latest_receipt = latest_id
