"""All settings come from environment variables (set them in Railway -> Variables)."""
import os


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


# --- Keys ---------------------------------------------------------------
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
TWELVEDATA_API_KEY = _env("TWELVEDATA_API_KEY")
X_AUTH_TOKEN = _env("X_AUTH_TOKEN")  # cookie "auth_token" from the separate X account
X_CT0 = _env("X_CT0")                # cookie "ct0" from the same account

# --- Models -------------------------------------------------------------
MODEL_SCOUT = _env("MODEL_SCOUT", "claude-haiku-5-5")
MODEL_HUNTER = _env("MODEL_HUNTER", "claude-haiku-5-5")
MODEL_ANALYST = _env("MODEL_ANALYST", "claude-sonnet-5-5")

# --- Markets ------------------------------------------------------------
# key -> Twelve Data symbol
SYMBOLS = {
    "XAUUSD": _env("GOLD_SYMBOL", "XAU/USD"),
    "OIL": _env("OIL_SYMBOL", "WTI/USD"),
}

# --- Schedule -----------------------------------------------------------
CYCLE_MINUTES = _int("CYCLE_MINUTES", 5)
TIMEZONE = _env("TIMEZONE", "Europe/Stockholm")
# Market week: opens Monday 00:00, closes Friday 23:00 (local TIMEZONE)
CLOSE_FRIDAY_HOUR = _int("CLOSE_FRIDAY_HOUR", 23)
ALWAYS_OPEN = _env("ALWAYS_OPEN") == "true"  # for testing on weekends

# --- Decision rules -----------------------------------------------------
ANALYST_MIN_CONF = _int("ANALYST_MIN_CONF", 65)
AVG_MIN_CONF = _int("AVG_MIN_CONF", 70)
RISK_MIN_PCT = _float("RISK_MIN_PCT", 0.5)   # risk per trade at AVG_MIN_CONF
RISK_MAX_PCT = _float("RISK_MAX_PCT", 2.0)   # risk per trade at 90+
SL_ATR_MULT = _float("SL_ATR_MULT", 1.5)
RR = _float("RR", 2.0)                       # take profit = RR x stop distance
START_BALANCE = _float("START_BALANCE", 10000)

# --- X accounts the Hunter follows ---------------------------------------
HUNTER_ACCOUNTS = [a.strip().lstrip("@") for a in _env(
    "HUNTER_ACCOUNTS", "realDonaldTrump,financialjuice,FirstSquawk,DeItaone"
).split(",") if a.strip()]

SCOUT_X_QUERIES = [q.strip() for q in _env(
    "SCOUT_X_QUERIES",
    "gold price|XAUUSD|crude oil|OPEC|Fed rate|oil supply|Middle East oil|dollar index",
).split("|") if q.strip()]

NEWS_FEEDS = [f.strip() for f in _env(
    "NEWS_FEEDS",
    "https://www.fxstreet.com/rss/news,"
    "https://oilprice.com/rss/main,"
    "https://www.investing.com/rss/news_11.rss,"
    "https://news.google.com/rss/search?q=gold+price+OR+crude+oil+OR+OPEC+OR+Federal+Reserve&hl=en-US&gl=US&ceid=US:en",
).split(",") if f.strip()]

TRUTH_FEED = _env("TRUTH_FEED", "https://www.trumpstruth.org/feed")

# --- Storage / web ------------------------------------------------------
DB_PATH = _env("DB_PATH", "data/agents.db")
DASHBOARD_PASSWORD = _env("DASHBOARD_PASSWORD")  # empty = no password
PORT = _int("PORT", 8000)

# Demo mode: fake data when keys are missing, so the site can be tested.
DEMO = _env("DEMO", "auto")


def demo_llm() -> bool:
    return DEMO == "true" or (DEMO == "auto" and not ANTHROPIC_API_KEY)


def demo_prices() -> bool:
    return DEMO == "true" or (DEMO == "auto" and not TWELVEDATA_API_KEY)
