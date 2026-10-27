"""Shared test data and helpers."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.appie.const import DOMAIN

TOKENS = {"access_token": "12345_abc", "refresh_token": "r1", "expires_at": 4_000_000_000}
# GET /mobile-services/bonuspage/v3/metadata, with the tabs appie-go bonus.go reads.
META = {"periods": [{"bonusStartDate": "2026-10-05", "bonusEndDate": "2026-10-11", "tabs": [{
    "description": "Alle bonus",
    "urlMetadataList": [
        {"url": "...", "count": 40, "bonusType": "NATIONAL", "description": "Groente, aardappelen"},
        {"url": "...", "count": 25, "bonusType": "NATIONAL", "description": "Zuivel, eieren"},
        {"url": "...", "count": 5, "bonusType": "PERSONAL", "description": "Persoonlijk"},
    ],
}]}]}

# GET /mobile-services/product/search/v2, shaped like appie-go doc/albertheijn_api.md.
SEARCH = {
    "products": [
        {"webshopId": 900, "title": "AH Halfvolle melk 2L", "salesUnitSize": "2 l", "currentPrice": 2.19,
         "isBonus": False, "isPreviouslyBought": False, "images": []},
        {"webshopId": 111, "title": "AH Roomboter", "salesUnitSize": "250 g", "currentPrice": 2.89,
         "priceBeforeBonus": 3.29, "isBonus": True, "bonusMechanism": "2e halve prijs",
         "isPreviouslyBought": True, "images": [{"width": 200, "height": 200, "url": "https://img.invalid/200"}]},
        {"webshopId": 901, "title": "Campina Halfvolle melk", "salesUnitSize": "1 l", "priceBeforeBonus": 1.59,
         "isBonus": False, "isPreviouslyBought": True},
    ],
    "page": {"number": 0, "size": 3, "totalElements": 3, "totalPages": 1},
}

# GraphQL FetchTotalPrice, the response from appie-go's API doc.
TOTAL_PRICE = {"data": {"totalPrice": {"withoutDiscount": {"amount": 5.58}, "discount": {"amount": 0.38}}}}

# POST /mobile-services/v2/recommendations/dontforgetlane, from appie-go's API doc.
DONT_FORGET = {
    "dataLakeModel": {"name": "TransformerModelWithCategory", "requestId": "", "version": "2026_02_01-11_50"},
    "productCards": [
        {"webshopId": 2600, "title": "AH Goudse jong 48+ plakken", "brand": "AH", "salesUnitSize": "190 g",
         "images": [{"width": 200, "height": 200, "url": "https://img.invalid/kaas"}], "isBonus": True,
         "bonusMechanism": "2e halve prijs", "priceBeforeBonus": 2.95, "currentPrice": 2.21},
        {"webshopId": 3100, "title": "AH Scharreleieren", "salesUnitSize": "10 stuks", "isBonus": False,
         "priceBeforeBonus": 3.49},
        # Already on the list: not suggested.
        {"webshopId": 111, "title": "AH Roomboter", "isBonus": False, "priceBeforeBonus": 3.29},
    ],
}

# GraphQL GetFavoriteStore, shaped like appie-go's API doc (dates around Tue 27 Oct 2026).
STORE = {"data": {"storesFavouriteStore": {
    "id": 1527,
    "address": {"street": "Nachtegaalstraat", "houseNumber": 48, "postalCode": "3581AD", "city": "Utrecht"},
    # Grouped per week, as AH sends it (seen on a live account).
    "openingDays": [[
        {"date": "2026-10-26", "openingHour": {"openFrom": "08:00", "openUntil": "22:00"}},
        {"date": "2026-10-27", "openingHour": {"openFrom": "08:00", "openUntil": "22:00"}},
        {"date": "2026-10-28", "openingHour": {"openFrom": "08:00", "openUntil": "00:00"}},
    ], [
        {"date": "2026-10-29", "openingHour": None},
    ]],
    "geoLocation": {"latitude": 52.09, "longitude": 5.12},
    "phone": "030-2345678",
    "storeType": "AH",
    "services": [{"code": "PICKUP"}, {"code": "SELFSERVICE"}],
}}}

# GraphQL bargainItems, as in appie-go koopjes_test.go; the second one is a product we often buy.
BARGAINS = {"data": {"bargainItems": [
    {"product": {"id": 12345, "title": "AH Roodbaarsfilet", "brand": "AH", "salesUnitSize": "ca. 200 g"},
     "categoryTitle": "Vis",
     "markdown": {"markdownType": "PERCENTAGE", "markdownExpirationDate": "2026-10-28", "markdownPercentage": 35.0},
     "stock": 3, "bargainPrice": {"priceWas": "5.99", "priceNow": "3.89"}},
    {"product": {"id": 111, "title": "AH Roomboter", "brand": "AH", "salesUnitSize": "250 g"},
     "categoryTitle": "Zuivel",
     "markdown": {"markdownType": "PERCENTAGE", "markdownExpirationDate": "2026-10-27", "markdownPercentage": 35.0},
     "stock": 1, "bargainPrice": {"priceWas": "3.29", "priceNow": "2.14"}},
]}}
# GET /mobile-services/product/detail/v4/fir/<id>, from appie-go's API doc.
PRODUCT_DETAIL = {
    "productId": 436752,
    "productCard": {
        "webshopId": 436752, "hqId": 60727, "title": "AH Biologisch Rundergehakt", "brand": "AH Biologisch",
        "salesUnitSize": "300 g", "mainCategory": "Vlees", "subCategory": "Rundergehakt",
        "images": [{"width": 200, "height": 200, "url": "https://img.invalid/gehakt"}],
        "currentPrice": 5.66, "priceBeforeBonus": 6.29, "isBonus": True, "bonusMechanism": "10% KORTING",
        "isFavorite": False, "isPreviouslyBought": True, "isOrderable": True, "availableOnline": True,
        "nutriscore": "D", "descriptionHighlights": "<p>Biologisch <b>rundergehakt</b></p>",
        "propertyIcons": ["biologisch"], "discountLabels": [],
    },
    "properties": [],
}

# GraphQL FetchProduct (nutrition), from appie-go's API doc.
NUTRITION = {"data": {"product": {"id": 436752, "tradeItem": {"nutritions": [{"nutrients": [
    {"type": "ENER-", "name": "Energie", "value": "1011 kJ (243 kcal)"},
    {"type": "FAT", "name": "Vet", "value": "18 g"},
]}]}}}}

# GET /mobile-services/bonuspage/v2/section/spotlight (same shape as a bonus section).
SPOTLIGHT = {"sectionType": "SPOTLIGHT", "bonusGroupOrProducts": [
    {"product": {"webshopId": 111, "title": "AH Roomboter", "bonusMechanism": "2e halve prijs", "currentPrice": 2.47,
                 "priceBeforeBonus": 3.29, "bonusEndDate": "2026-10-11"}},
    {"bonusGroup": {"id": "g7", "segmentId": 700, "segmentDescription": "Alle Lay's chips",
                    "discountDescription": "1 + 1 GRATIS", "products": [{"webshopId": 701}]}},
]}

# GraphQL FetchBonusBoxOffers, the example response from appie-go's API doc (plus one more offer).
BONUS_BOX = {"data": {
    "bonusPersonalPromotionBundles": [{"maximumActivations": 10, "error": None}],
    "bonusPromotions": [
        {"id": "385568", "hqId": 894018, "title": "AH Pancakes", "activationStatus": "ACTIVATED",
         "category": "Maaltijden, salades", "promotionType": "PERSONAL", "segmentType": "BONUS_BOX",
         "periodStart": "2026-02-09", "periodEnd": "2026-02-15",
         "rawPromotionLabels": [{"mechanism": "PRICE", "price": 2.0, "defaultDescription": "VOOR 2.00"}],
         "price": {"now": {"amount": 2.0}, "was": {"amount": 2.99}}},
        {"id": "385569", "hqId": 894019, "title": "AH Hummus", "activationStatus": "ACTIVATABLE",
         "category": "Salades", "periodStart": "2026-02-09", "periodEnd": "2026-02-15",
         "rawPromotionLabels": [], "price": None},
    ],
}}

# GraphQL FetchFavoriteLists, shaped like appie-go's API doc.
FAVORITE_LISTS = {"data": {"favoriteListV2": [
    {"__typename": "FavoriteListV2", "id": "305e6a50-a970-457b-8831-409f572832d4",
     "description": "Weekboodschappen", "totalSize": 3, "imageUrl": "https://img.invalid/lijst"},
    {"__typename": "FavoriteListV2", "id": "aaaa0000-0000-0000-0000-000000000001",
     "description": "Feestje", "totalSize": 0, "imageUrl": None},
]}}

# GraphQL favoriteListV2 with items, as queried in appie-go shoppinglist.go.
FAVORITE_LIST_ITEMS = {"data": {"favoriteListV2": [{
    "id": "305E6A50-A970-457B-8831-409F572832D4", "description": "Weekboodschappen", "totalSize": 3,
    "items": [
        {"id": "i1", "productId": 111, "quantity": 1},
        {"id": "i2", "productId": 222, "quantity": 3},
        {"id": "i3", "productId": 555, "quantity": 1},
    ],
}]}}


async def setup_appie(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="12345", data=TOKENS, title="Albert Heijn", options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# Savings, in the shapes of doc/graphql-schema-20260118.md.
STAMPS = {
    "points": {"totalPoints": 212, "currentBookletPoints": 32, "fullBooklets": 1},
    "money": {"invested": {"amount": 21.2}, "interest": {"amount": 0.54}, "payout": {"amount": 21.74}},
    "constants": {
        "price": {"amount": 0.1},
        "partialBookletTarget": {"points": 90, "interest": {"amount": 0.27}},
        "fullBookletTarget": {"points": 180, "interest": {"amount": 0.54}},
    },
}
MILES = {"balance": 1234, "errorState": None}
LOYALTY = {
    "loyaltyPrograms": [
        {
            "id": 7, "name": "pannen", "type": "STAMPS", "status": "ACTIVE",
            "savingPeriod": {"start": "2026-10-01", "end": "2099-12-31"},
            "redeemPeriod": {"start": "2026-10-01", "end": "2099-12-31"},
            "content": {"title": "Spaar voor pannen", "subtitle": "1 zegel per 10 euro", "stamps": {"stampsPerCard": 30}},
        },
        {
            "id": 3, "name": "oud", "type": "STAMPS", "status": "ENDED",
            "savingPeriod": {"start": "2020-01-01", "end": "2020-02-01"},
            "redeemPeriod": {"start": "2020-01-01", "end": "2020-03-01"},
            "content": {"title": "Oude actie"},
        },
    ],
    "loyaltyChallenges": [
        {
            "id": 5, "name": "fruit", "status": "OPTED_IN", "statusMessage": None,
            "info": {"title": "Fruitweek", "description": "Koop 3 keer fruit"},
            "reward": {"label": "100 koopzegels", "subtitle": None, "duration": {"start": "2099-01-01", "end": "2099-01-31"}},
            "steps": [
                {"id": 1, "status": "IN_PROGRESS", "label": "Koop fruit", "subtitle": "3 keer", "progress": 1,
                 "maxProgress": 3, "duration": {"start": "2026-10-20", "end": "2099-01-01"},
                 "progressDetails": {"progress": "1", "remainingProgress": "2", "total": "3"}},
            ],
        }
    ],
}
LOYALTY_BALANCES = [{"programId": 7, "balance": 12}]
PREMIUM = {
    "subscriptionCurrent": {
        "description": "AH Premium", "isActive": True, "isTrialSubscription": False,
        "startDate": "2026-01-01", "endDate": "2026-12-31", "sellPrice": {"amount": 39.0},
        "extension": {"date": "2027-01-01", "sellPrice": {"amount": 39.0}},
    },
    "subscriptionEstimatedPremiumSavings": {
        "subscriptionActiveDays": 300, "estimatedYearlySavedAmount": 123.456, "estimatedYearlySavedStampsAmount": 900,
        "estimatedRemainingDaysSavedAmount": 20.5, "averageDailySavedAmount": 0.34,
    },
    "subscriptionSavingPotential": {"premiumSavingPotential": 50.0},
    "subscriptionPremiumSavingsV2": {
        "lastUpdated": "2026-10-26", "subscriptionStartDate": "2023-08-12", "totalSavedAmount": {"amount": 191.31},
        "bonusBoxDiscountAmount": {"amount": 178.21}, "bonusBoxDiscountPremiumExclusiveAmount": {"amount": 20.0},
        "bioDiscountAmount": {"amount": 3.99}, "deliveryBundleDiscountAmount": None, "additionalAirmilesObtained": 4464,
        "additionalAirmilesObtainedInMoney": {"amount": 44.64}, "additionalPurchaseStampsObtained": 12442,
        "additionalPurchaseStampsInterest": {"amount": 2.5}, "totalAdditionalStamps": 12442,
    },
}
WALLET = {
    "paymentsGetGiftCards": [
        {"cardNumber": "6299001234567890", "status": "ACTIVE", "createdDate": "2026-05-01T10:00:00Z",
         "balance": {"amount": {"amount": 25.0}}},
    ],
    "settlementsTotal": {"totalAmount": {"amount": 3.5}, "settlements": [{"__typename": "SettlementV2"}]},
}
