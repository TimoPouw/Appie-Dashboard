"""Constants for the Albert Heijn integration."""

from datetime import timedelta

DOMAIN = "appie"

API_BASE = "https://api.ah.nl"
LOGIN_URL = (
    "https://login.ah.nl/login?client_id=appie-ios"
    "&response_type=code&redirect_uri=appie://login-exit"
)
CLIENT_ID = "appie-ios"
CLIENT_VERSION = "9.28"
APPLICATION = "AHWEBSHOP"
USER_AGENT = f"Appie/{CLIENT_VERSION} (iPhone17,3; iPhone; CPU OS 26_1 like Mac OS X)"

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"

# Refresh the 7-day access token once less than this is left.
TOKEN_REFRESH_MARGIN = timedelta(days=1)

LIST_INTERVAL = timedelta(seconds=60)
BONUS_INTERVAL = timedelta(hours=6)
RECEIPTS_INTERVAL = timedelta(hours=1)
FAVORITES_INTERVAL = timedelta(hours=12)
# Follows list changes; prices themselves change with the bonus week.
LIST_COST_INTERVAL = timedelta(hours=6)
# The first list edit is priced right away; a burst after it (ticking off five
# items) costs one more call, at the end of this cooldown.
LIST_COST_COOLDOWN = 60
# "Vergeet niet": at most once per 15 minutes after a list change, else every 6 h.
DONT_FORGET_INTERVAL = timedelta(hours=6)
DONT_FORGET_COOLDOWN = 15 * 60
# Opening hours barely change; koopjes change during the day, only while open.
STORE_INTERVAL = timedelta(hours=12)
BARGAINS_INTERVAL = timedelta(minutes=30)
EVENT_BARGAIN_FAVORITE = "appie_koopje_favoriet"
FAVORITE_LISTS_INTERVAL = timedelta(minutes=30)

# How many receipts to fetch per update (covers well over a month).
RECEIPTS_PAGE_SIZE = 50

# "Vaak gekocht" buttons: how many, counted over how many days of receipts.
# Defaults; both can be changed in the options.
CONF_FAVORITES_COUNT = "favorites_count"
CONF_FAVORITES_DAYS = "favorites_days"
FAVORITES_COUNT = 10
FAVORITES_DAYS = 120
FAVORITES_COUNT_RANGE = (10, 50)
FAVORITES_DAYS_RANGE = (30, 365)
