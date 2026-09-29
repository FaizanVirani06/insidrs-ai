import os
from dataclasses import dataclass
from typing import Optional

# Optional: load a local .env file if present.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # If python-dotenv isn't installed or .env isn't present, that's fine.
    pass


def _env_bool(name: str, default: Optional[bool] = None) -> Optional[bool]:
    """Parse a boolean environment variable.

    Returns:
      - True/False if the env var is set to a recognizable value
      - default if unset or unrecognized

    Accepted truthy: 1, true, yes, y, on
    Accepted falsy:  0, false, no, n, off
    """

    raw = os.environ.get(name)
    if raw is None:
        return default
    v = raw.strip().lower()
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    return default


@dataclass(frozen=True)
class Config:
    """Runtime configuration.

    IMPORTANT: Provide API keys via environment variables or a .env file.
    Do not hardcode secrets in source code.
    """

    # -----------------
    # Core
    # -----------------
    # Database (PostgreSQL)
    # Preferred: set INSIDER_DATABASE_URL (or DATABASE_URL).
    # Default is a local dev Postgres matching docker-compose.yml.
    DB_DSN: str = (
        os.environ.get("INSIDER_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql://postgres:postgres@localhost:5432/insider_platform"
    )

    # SEC (EDGAR requires a descriptive User-Agent)
    SEC_USER_AGENT: str = os.environ.get(
        "SEC_USER_AGENT",
        "InsiderPlatform/0.1 (contact: you@example.com)",
    )

    # EODHD
    EODHD_API_KEY: str | None = os.environ.get("EODHD_API_KEY")
    EODHD_BASE_URL: str = os.environ.get("EODHD_BASE_URL", "https://eodhd.com/api")

    # Cache staleness
    MARKET_CAP_MAX_AGE_DAYS: int = int(os.environ.get("MARKET_CAP_MAX_AGE_DAYS", "7"))
    NEWS_MAX_AGE_HOURS: int = int(os.environ.get("NEWS_MAX_AGE_HOURS", "12"))

    # Gemini
    GEMINI_API_KEY: str | None = os.environ.get("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    GEMINI_BASE_URL: str = os.environ.get(
        "GEMINI_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta",
    )

    # AI generation
    AI_TEMPERATURE: float = float(os.environ.get("AI_TEMPERATURE", "0.2"))
    AI_MAX_TOKENS: int = int(os.environ.get("AI_MAX_TOKENS", "2048"))

    # Yahoo Finance (market cap)
    YAHOO_QUOTE_URL: str = os.environ.get(
        "YAHOO_QUOTE_URL",
        "https://query1.finance.yahoo.com/v7/finance/quote",
    )

    # Versions (bump when behavior changes)
    # v1.2: event_trade_date now prefers earliest open-market date (improves trend/outcomes anchoring)
    CURRENT_PARSE_VERSION: str = os.environ.get("CURRENT_PARSE_VERSION", "form4_parse_v1.2")
    OWNER_NORM_VERSION: str = os.environ.get("OWNER_NORM_VERSION", "owner_norm_v1")
    # v2: require >=2 distinct filings in a cluster window (reduces false positives from multi-owner filings)
    CURRENT_CLUSTER_VERSION: str = os.environ.get("CURRENT_CLUSTER_VERSION", "cluster_v2")
    # v2: trend anchoring prefers earliest open-market date when present
    CURRENT_TREND_VERSION: str = os.environ.get("CURRENT_TREND_VERSION", "trend_v2")
    # v3: outcomes anchor on filing_date (tradeable) and use adjusted-close p0 (split-safe)
    CURRENT_OUTCOMES_VERSION: str = os.environ.get("CURRENT_OUTCOMES_VERSION", "outcomes_v3")
    CURRENT_STATS_VERSION: str = os.environ.get("CURRENT_STATS_VERSION", "stats_v2")

    AI_INPUT_SCHEMA_VERSION: str = os.environ.get("AI_INPUT_SCHEMA_VERSION", "ai_input_v2")
    AI_OUTPUT_SCHEMA_VERSION: str = os.environ.get("AI_OUTPUT_SCHEMA_VERSION", "ai_output_v1")
    PROMPT_VERSION: str = os.environ.get("PROMPT_VERSION", "prompt_ai_v5")

    # Benchmark (excess returns) - used for insider performance stats
    BENCHMARK_SYMBOL: str = os.environ.get("BENCHMARK_SYMBOL", "SPY.US")  # S&P500 proxy

    # Backfill (historical filings ingestion)
    BACKFILL_START_YEAR: int = int(os.environ.get("BACKFILL_START_YEAR", "2006"))
    BACKFILL_BATCH_SIZE: int = int(os.environ.get("BACKFILL_BATCH_SIZE", "50"))

    # SEC throttling (polite rate limiting).
    SEC_MIN_INTERVAL_SECONDS: float = float(os.environ.get("SEC_MIN_INTERVAL_SECONDS", "0.12"))

    # Worker
    WORKER_POLL_SECONDS: float = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))

    # Optional: SEC "current" Form 4 poller.
    # If enabled, the worker will periodically poll the SEC current filings feed
    # and enqueue ingestion jobs for tracked issuers.
    ENABLE_FORM4_POLLER: bool = _env_bool("ENABLE_FORM4_POLLER", False) is True
    FORM4_POLLER_INTERVAL_SECONDS: int = int(os.environ.get("FORM4_POLLER_INTERVAL_SECONDS", "120"))
    FORM4_POLLER_FEED_URL: str = os.environ.get(
        "FORM4_POLLER_FEED_URL",
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&owner=only&count=200&output=atom",
    )

    # -----------------
    # Auth (JWT)
    # -----------------
    # NOTE: In dev, this defaults to a fixed string so you can get started.
    # In production, you MUST set AUTH_JWT_SECRET to a strong random value.
    AUTH_JWT_SECRET: str = os.environ.get("AUTH_JWT_SECRET", "dev_change_me")
    AUTH_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("AUTH_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 days

    # Bootstrap first admin user if users table is empty
    AUTH_BOOTSTRAP_ADMIN_USERNAME: str = os.environ.get("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin")
    AUTH_BOOTSTRAP_ADMIN_PASSWORD: str = os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "admin")

    # Cookie-based browser sessions (recommended for the new non-Next frontend)
    # - The API will set an httpOnly cookie on /auth/login and /auth/register
    # - The API will read the token from either Authorization: Bearer ... OR the cookie
    AUTH_COOKIE_NAME: str = os.environ.get("AUTH_COOKIE_NAME", "ip_token")
    AUTH_COOKIE_DOMAIN: str | None = (os.environ.get("AUTH_COOKIE_DOMAIN") or "").strip() or None
    AUTH_COOKIE_PATH: str = os.environ.get("AUTH_COOKIE_PATH", "/")
    AUTH_COOKIE_SAMESITE: str = os.environ.get("AUTH_COOKIE_SAMESITE", "lax")  # lax|strict|none

    # If AUTH_COOKIE_SECURE is unset, we default to secure cookies when PUBLIC_APP_URL is https.
    # You can override explicitly with AUTH_COOKIE_SECURE=0/1.
    # NOTE: Browsers require Secure when SameSite=None.
    PUBLIC_APP_URL: str = os.environ.get("PUBLIC_APP_URL", "http://localhost:5173")
    AUTH_COOKIE_SECURE: bool = (
        _env_bool("AUTH_COOKIE_SECURE", None)
        if _env_bool("AUTH_COOKIE_SECURE", None) is not None
        else PUBLIC_APP_URL.lower().startswith("https://")
    )

    # -----------------
    # CORS (development)
    # -----------------
    # If you develop with Vite on :5173 and API on :8000, enable credentials + allow that origin.
    # In production (same origin behind a reverse proxy) CORS is not required.
    CORS_ALLOW_ORIGINS: str = os.environ.get(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000",
    )

    # -----------------
    # Billing (Stripe)
    # -----------------
    # Stripe API keys (required for paid gating + checkout)
    STRIPE_SECRET_KEY: str | None = os.environ.get("STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET: str | None = os.environ.get("STRIPE_WEBHOOK_SECRET")

    # Price IDs configured in Stripe (Subscription mode). You can use one or both.
    STRIPE_PRICE_ID_MONTHLY: str | None = os.environ.get("STRIPE_PRICE_ID_MONTHLY")
    STRIPE_PRICE_ID_YEARLY: str | None = os.environ.get("STRIPE_PRICE_ID_YEARLY")

    # Optional monthly free trial shown on the pricing page / Checkout.
    # Set to 0 to disable the trial CTA without changing code.
    STRIPE_MONTHLY_TRIAL_DAYS: int = max(0, int(os.environ.get("STRIPE_MONTHLY_TRIAL_DAYS", "7")))

    # Optional: allow a free internal bypass for development.
    # If set to 1, users are treated as paid even without an active Stripe subscription.
    BILLING_DEV_BYPASS: bool = _env_bool("BILLING_DEV_BYPASS", False) is True

    # X/Twitter posting (admin tool)
    X_API_KEY: str | None = os.environ.get("X_API_KEY")
    X_API_SECRET: str | None = os.environ.get("X_API_SECRET")
    X_ACCESS_TOKEN: str | None = os.environ.get("X_ACCESS_TOKEN")
    X_ACCESS_TOKEN_SECRET: str | None = os.environ.get("X_ACCESS_TOKEN_SECRET")
    X_POSTING_ENABLED: bool = _env_bool("X_POSTING_ENABLED", False) is True
    X_HANDLE: str | None = os.environ.get("X_HANDLE")

    # Automatic trade plan generation.
    # Internal AI ratings are 1-10; the UI displays these as 1-100.
    TRADE_PLAN_MIN_BUY_RATING: float = float(os.environ.get("TRADE_PLAN_MIN_BUY_RATING", "6.0"))

    # Portfolio showcase mode (default on).
    # - Paywall off: every signed-in user gets full access.
    # - Stripe checkout closed.
    # - Public one-click demo login (read-only showcase account, PII masked).
    # - Leaderboard anchored to the last date with stored price data (market data is frozen).
    # Set SHOWCASE_MODE=0 to restore normal paid-product behavior.
    SHOWCASE_MODE: bool = _env_bool("SHOWCASE_MODE", True) is True


def load_config() -> Config:
    return Config()
