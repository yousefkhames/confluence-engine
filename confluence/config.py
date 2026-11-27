"""Central configuration. Everything is overridable by environment variables."""
import os

DB_PATH = os.environ.get("CONFLUENCE_DB", "data/confluence.db")

# Phase 1 focus: the largest liquid coins only (spec: top 20).
COINS = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "LTC",
         "BCH", "ATOM", "UNI", "NEAR", "APT", "ARB", "OP", "AAVE", "FIL", "ETC"]
# Public Coinbase Exchange product ids (no key needed). Binance is geo-blocked in some regions.
PRODUCT = {c: f"{c}-USD" for c in COINS}

SECTORS = {
    "L1": ["ETH", "SOL", "ADA", "AVAX", "DOT", "NEAR", "APT", "ATOM"],
    "L2": ["ARB", "OP"],
    "DeFi": ["UNI", "AAVE", "LINK"],
    "Store": ["BTC", "LTC", "BCH", "ETC"],
    "Payments": ["XRP", "DOGE"],
}

WHALE_USD_MIN = float(os.environ.get("WHALE_USD_MIN", 500_000))  # spec example: > $500k

# Confluence weights (sum to 1). Phase 2 adjusts these from the signal log.
DEFAULT_WEIGHTS = {"whale": 0.40, "news": 0.30, "sentiment": 0.30}

SIGNAL_THRESHOLD = float(os.environ.get("SIGNAL_THRESHOLD", 60))  # score needed to emit
SIGNAL_COOLDOWN_S = 3600  # one signal per coin per hour
HORIZONS = {"15m": 900, "1h": 3600, "4h": 14400, "24h": 86400}

# Cost model for the Net Edge calculator (percent of notional).
FEE_PCT = 0.10       # per side, typical spot taker
SLIPPAGE_PCT = 0.05  # per side, large-cap default

# Price-in: news older than this is ignored for the unpriced-catalyst factor.
NEWS_WINDOW_S = 3600
WHALE_WINDOW_S = 6 * 3600
SOCIAL_WINDOW_S = 3600
LATE_MOVE_PCT = 15.0   # spec: price already flew 15% -> too late

TIERS = {
    "free":  {"delay_s": 900, "max_coins": 5, "alerts": False, "api": False, "price_usd": 0},
    "pro":   {"delay_s": 0,   "max_coins": 20, "alerts": True, "api": False, "price_usd": 79},
    "quant": {"delay_s": 0,   "max_coins": 20, "alerts": True, "api": True, "price_usd": 299},
}
