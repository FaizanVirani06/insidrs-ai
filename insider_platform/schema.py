from __future__ import annotations

"""Database schema for Insider Platform.

PostgreSQL is the only supported database engine.
"""

# NOTE:
# - We store timestamps as ISO strings (UTC, ending with 'Z') for simplicity.
# - This schema is intentionally light on constraints; application code enforces most invariants.

SCHEMA_POSTGRES = r"""CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Users / Auth
-- NOTE: This is intentionally simple (username/password + role).
-- We use JWTs for stateless auth and store only password hashes.
CREATE TABLE IF NOT EXISTS users (
    user_id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','showcase','user')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT,

    -- Billing / subscription (Stripe)
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    stripe_price_id TEXT,
    subscription_status TEXT, -- e.g. active|trialing|past_due|canceled
    current_period_end TEXT,
    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
    subscription_updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_role_active ON users (role, is_active);
CREATE INDEX IF NOT EXISTS idx_users_stripe_customer ON users (stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_users_subscription_status ON users (subscription_status, is_active);

-- User profile + recommendation preferences
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id BIGINT PRIMARY KEY,
    full_name TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    preferences_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_user_profiles_contact_email ON user_profiles (contact_email);

-- Feedback (customers)
CREATE TABLE IF NOT EXISTS user_feedback (
    feedback_id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    page_url TEXT,
    rating INTEGER,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_feedback_user_created ON user_feedback (user_id, created_at);

-- Support chat (in-app)
-- A lightweight "ticket thread" model: one thread contains many messages.
-- This enables a simple support widget for users and an admin inbox.
CREATE TABLE IF NOT EXISTS support_threads (
    thread_id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_message_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_support_threads_user_status ON support_threads (user_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_support_threads_status_updated ON support_threads (status, updated_at);

CREATE TABLE IF NOT EXISTS support_messages (
    message_id BIGSERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL,
    sender_role TEXT NOT NULL CHECK (sender_role IN ('user','admin')),
    sender_user_id INTEGER,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES support_threads(thread_id),
    FOREIGN KEY (sender_user_id) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_support_messages_thread_created ON support_messages (thread_id, created_at);

-- Stripe webhook idempotency
CREATE TABLE IF NOT EXISTS stripe_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issuer_master (
    issuer_cik TEXT PRIMARY KEY,
    current_ticker TEXT,
    ticker_updated_at TEXT,
    issuer_name TEXT,
    last_filing_date TEXT
);
CREATE INDEX IF NOT EXISTS idx_issuer_master_current_ticker ON issuer_master (current_ticker);
CREATE INDEX IF NOT EXISTS idx_issuer_master_last_filing_date ON issuer_master (last_filing_date);


CREATE TABLE IF NOT EXISTS filings (
    accession_number TEXT PRIMARY KEY,
    issuer_cik TEXT NOT NULL,
    ticker_reported TEXT,
    form_type TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    source_url TEXT,
    parse_version TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_filings_issuer_date ON filings (issuer_cik, filing_date);

CREATE TABLE IF NOT EXISTS filing_documents (
    accession_number TEXT PRIMARY KEY,
    issuer_cik TEXT,
    filing_date TEXT,
    form_type TEXT,
    source_url TEXT,
    xml_text TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_filing_documents_issuer ON filing_documents (issuer_cik);

CREATE TABLE IF NOT EXISTS form4_rows_raw (
    row_id BIGSERIAL PRIMARY KEY,
    accession_number TEXT NOT NULL,
    issuer_cik TEXT NOT NULL,
    owner_key TEXT NOT NULL,
    owner_cik TEXT,
    owner_name_raw TEXT,
    owner_name_normalized TEXT,
    owner_name_hash TEXT,
    is_derivative INTEGER NOT NULL,
    transaction_code TEXT,
    transaction_date TEXT,
    shares_raw DOUBLE PRECISION,
    shares_abs DOUBLE PRECISION,
    price_raw TEXT,
    price DOUBLE PRECISION,
    shares_owned_following DOUBLE PRECISION,
    parser_warnings_json TEXT,
    raw_payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rows_accession ON form4_rows_raw (accession_number);
CREATE INDEX IF NOT EXISTS idx_rows_eventkey ON form4_rows_raw (issuer_cik, owner_key, accession_number);
CREATE INDEX IF NOT EXISTS idx_rows_issuer_code_date ON form4_rows_raw (issuer_cik, transaction_code, transaction_date);

CREATE TABLE IF NOT EXISTS insider_events (
    issuer_cik TEXT NOT NULL,
    owner_key TEXT NOT NULL,
    accession_number TEXT NOT NULL,

    ticker TEXT,
    filing_date TEXT NOT NULL,
    event_trade_date TEXT,

    owner_cik TEXT,
    owner_name_display TEXT,
    owner_title TEXT,
    is_officer INTEGER,
    is_director INTEGER,
    is_ten_percent_owner INTEGER,

    -- Buy (P)
    has_buy INTEGER NOT NULL DEFAULT 0,
    buy_trade_date TEXT,
    buy_last_tx_date TEXT,
    buy_shares_total DOUBLE PRECISION,
    buy_dollars_total DOUBLE PRECISION,
    buy_vwap_price DOUBLE PRECISION,
    buy_priced_shares_total DOUBLE PRECISION,
    buy_unpriced_shares_total DOUBLE PRECISION,
    buy_vwap_is_partial INTEGER,
    buy_shares_owned_following DOUBLE PRECISION,
    buy_pct_holdings_change DOUBLE PRECISION,
    buy_pct_change_missing_reason TEXT,

    -- Sell (S)
    has_sell INTEGER NOT NULL DEFAULT 0,
    sell_trade_date TEXT,
    sell_last_tx_date TEXT,
    sell_shares_total DOUBLE PRECISION,
    sell_dollars_total DOUBLE PRECISION,
    sell_vwap_price DOUBLE PRECISION,
    sell_priced_shares_total DOUBLE PRECISION,
    sell_unpriced_shares_total DOUBLE PRECISION,
    sell_vwap_is_partial INTEGER,
    sell_shares_owned_following DOUBLE PRECISION,
    sell_pct_holdings_change DOUBLE PRECISION,
    sell_pct_change_missing_reason TEXT,

    -- Summaries
    non_open_market_row_count INTEGER NOT NULL DEFAULT 0,
    derivative_row_count INTEGER NOT NULL DEFAULT 0,

    -- Trend context (event-level)
    trend_anchor_trading_date TEXT,
    trend_close DOUBLE PRECISION,
    trend_ret_20d DOUBLE PRECISION,
    trend_ret_60d DOUBLE PRECISION,
    trend_dist_52w_high DOUBLE PRECISION,
    trend_dist_52w_low DOUBLE PRECISION,
    trend_above_sma_50 INTEGER,
    trend_above_sma_200 INTEGER,
    trend_missing_reason TEXT,

    -- Cluster
    cluster_flag_buy INTEGER,
    cluster_id_buy TEXT,
    cluster_flag_sell INTEGER,
    cluster_id_sell TEXT,

    -- Market cap snapshot (denormalized)
    market_cap BIGINT,
    market_cap_bucket TEXT,
    market_cap_updated_at TEXT,

    -- AI snapshot (denormalized)
    ai_buy_rating DOUBLE PRECISION,
    ai_sell_rating DOUBLE PRECISION,
    ai_confidence DOUBLE PRECISION,
    ai_model_id TEXT,
    ai_prompt_version TEXT,
    ai_generated_at TEXT,

    -- Versions and timestamps
    parse_version TEXT NOT NULL,
    event_computed_at TEXT NOT NULL,
    trend_computed_at TEXT,
    outcomes_computed_at TEXT,
    stats_computed_at TEXT,
    cluster_computed_at TEXT,
    ai_computed_at TEXT,

    PRIMARY KEY (issuer_cik, owner_key, accession_number)
);
CREATE INDEX IF NOT EXISTS idx_events_ticker_date ON insider_events (ticker, filing_date);
CREATE INDEX IF NOT EXISTS idx_events_issuer_owner_date ON insider_events (issuer_cik, owner_key, filing_date);
CREATE INDEX IF NOT EXISTS idx_events_ticker_trade ON insider_events (ticker, event_trade_date);
CREATE INDEX IF NOT EXISTS idx_events_cluster_buy ON insider_events (ticker, cluster_flag_buy);
CREATE INDEX IF NOT EXISTS idx_events_cluster_sell ON insider_events (ticker, cluster_flag_sell);

CREATE TABLE IF NOT EXISTS event_outcomes (
    issuer_cik TEXT NOT NULL,
    owner_key TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy','sell')),

    trade_date TEXT,
    anchor_trading_date TEXT,
    p0 DOUBLE PRECISION,

    future_date_60d TEXT,
    future_price_60d DOUBLE PRECISION,
    return_60d DOUBLE PRECISION,
    missing_reason_60d TEXT,

    bench_symbol TEXT,
    bench_return_60d DOUBLE PRECISION,
    bench_missing_reason_60d TEXT,
    excess_return_60d DOUBLE PRECISION,

    future_date_180d TEXT,
    future_price_180d DOUBLE PRECISION,
    return_180d DOUBLE PRECISION,
    missing_reason_180d TEXT,

    bench_return_180d DOUBLE PRECISION,
    bench_missing_reason_180d TEXT,
    excess_return_180d DOUBLE PRECISION,

    outcomes_version TEXT NOT NULL,
    computed_at TEXT NOT NULL,

    PRIMARY KEY (issuer_cik, owner_key, accession_number, side)
);
CREATE INDEX IF NOT EXISTS idx_outcomes_issuer_owner_side ON event_outcomes (issuer_cik, owner_key, side);

CREATE TABLE IF NOT EXISTS issuer_prices_daily (
    issuer_cik TEXT NOT NULL,
    date TEXT NOT NULL,
    adj_close DOUBLE PRECISION NOT NULL,
    source_ticker TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (issuer_cik, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_issuer_date ON issuer_prices_daily (issuer_cik, date);

CREATE TABLE IF NOT EXISTS issuer_ticker_validation (
    issuer_cik TEXT NOT NULL,
    ticker TEXT NOT NULL,
    eodhd_symbol TEXT,
    status TEXT NOT NULL CHECK (status IN ('valid','invalid','unknown')),
    issuer_name TEXT,
    provider_name TEXT,
    provider_code TEXT,
    provider_exchange TEXT,
    match_score DOUBLE PRECISION,
    reason TEXT,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (issuer_cik, ticker)
);
CREATE INDEX IF NOT EXISTS idx_ticker_validation_status ON issuer_ticker_validation (status, checked_at);

CREATE TABLE IF NOT EXISTS benchmark_prices_daily (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    adj_close DOUBLE PRECISION NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_benchmark_prices_symbol_date ON benchmark_prices_daily (symbol, date);


CREATE TABLE IF NOT EXISTS clusters (
    cluster_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    issuer_cik TEXT,
    side TEXT NOT NULL CHECK (side IN ('buy','sell')),
    window_start_date TEXT NOT NULL,
    window_end_date TEXT NOT NULL,
    unique_insiders INTEGER NOT NULL,
    total_dollars DOUBLE PRECISION NOT NULL,
    execs_involved INTEGER NOT NULL,
    max_pct_holdings_change DOUBLE PRECISION,
    cluster_version TEXT NOT NULL,
    computed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clusters_ticker_side_window ON clusters (ticker, side, window_start_date, window_end_date);

CREATE TABLE IF NOT EXISTS cluster_members (
    cluster_id TEXT NOT NULL,
    issuer_cik TEXT NOT NULL,
    owner_key TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy','sell')),
    trade_date TEXT NOT NULL,
    dollars_contributed DOUBLE PRECISION,
    pct_holdings_change DOUBLE PRECISION,
    PRIMARY KEY (cluster_id, issuer_cik, owner_key, accession_number, side)
);
CREATE INDEX IF NOT EXISTS idx_cluster_members_event ON cluster_members (issuer_cik, owner_key, accession_number, side);

CREATE TABLE IF NOT EXISTS insider_issuer_stats (
    issuer_cik TEXT NOT NULL,
    owner_key TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy','sell')),

    eligible_n_60d INTEGER NOT NULL,
    win_rate_60d DOUBLE PRECISION,
    avg_return_60d DOUBLE PRECISION,

    eligible_n_180d INTEGER NOT NULL,
    win_rate_180d DOUBLE PRECISION,
    avg_return_180d DOUBLE PRECISION,

    stats_version TEXT NOT NULL,
    computed_at TEXT NOT NULL,

    PRIMARY KEY (issuer_cik, owner_key, side)
);
CREATE INDEX IF NOT EXISTS idx_stats_issuer_owner ON insider_issuer_stats (issuer_cik, owner_key);

CREATE TABLE IF NOT EXISTS market_cap_cache (
    ticker TEXT PRIMARY KEY,
    market_cap BIGINT,
    market_cap_bucket TEXT,
    market_cap_source TEXT NOT NULL DEFAULT 'eodhd',
    market_cap_updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_outputs (
    ai_output_id BIGSERIAL PRIMARY KEY,
    issuer_cik TEXT NOT NULL,
    owner_key TEXT NOT NULL,
    accession_number TEXT NOT NULL,

    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_schema_version TEXT NOT NULL,
    output_schema_version TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,

    buy_rating DOUBLE PRECISION,
    sell_rating DOUBLE PRECISION,
    confidence DOUBLE PRECISION,

    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_event ON ai_outputs (issuer_cik, owner_key, accession_number);
CREATE INDEX IF NOT EXISTS idx_ai_inputs_hash ON ai_outputs (inputs_hash);

CREATE TABLE IF NOT EXISTS backfill_queue (
    issuer_cik TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    filing_date TEXT,
    form_type TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending','queued','fetched','parsed','error')),
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (issuer_cik, accession_number)
);
CREATE INDEX IF NOT EXISTS idx_backfill_status ON backfill_queue (status, issuer_cik, filing_date);

CREATE TABLE IF NOT EXISTS jobs (
    job_id BIGSERIAL PRIMARY KEY,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','running','success','error')),
    priority INTEGER NOT NULL DEFAULT 100,
    dedupe_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    run_after TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_priority ON jobs (status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_run_after ON jobs (run_after);

CREATE TABLE IF NOT EXISTS data_issues (
    issue_id BIGSERIAL PRIMARY KEY,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
    issuer_cik TEXT,
    ticker TEXT,
    accession_number TEXT,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

-- EODHD fundamentals cache (store raw JSON + extracted highlights for AI/context)
CREATE TABLE IF NOT EXISTS issuer_fundamentals_cache (
    ticker TEXT PRIMARY KEY,
    eodhd_symbol TEXT,
    market_cap BIGINT,
    pe_ratio DOUBLE PRECISION,
    eps DOUBLE PRECISION,
    shares_outstanding DOUBLE PRECISION,
    sector TEXT,
    beta DOUBLE PRECISION,
    fundamentals_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fundamentals_updated_at ON issuer_fundamentals_cache (updated_at);

-- EODHD news cache (store recent headlines / sentiment)
CREATE TABLE IF NOT EXISTS issuer_news (
    ticker TEXT NOT NULL,
    published_at TEXT,
    title TEXT,
    source TEXT,
    url TEXT NOT NULL,
    sentiment DOUBLE PRECISION,
    summary TEXT,
    news_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (ticker, url)
);
CREATE INDEX IF NOT EXISTS idx_news_ticker_published ON issuer_news (ticker, published_at);

CREATE TABLE IF NOT EXISTS social_posts (
    post_id BIGSERIAL PRIMARY KEY,
    platform TEXT NOT NULL DEFAULT 'x',
    status TEXT NOT NULL CHECK (status IN ('draft','posted','failed','dry_run')),
    content TEXT NOT NULL,
    link_url TEXT,
    x_tweet_id TEXT,
    x_tweet_url TEXT,
    error_message TEXT,
    source_signal_id TEXT,
    created_by_user_id BIGINT,
    created_at TEXT NOT NULL,
    posted_at TEXT,
    FOREIGN KEY (created_by_user_id) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_social_posts_created ON social_posts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_posts_source_signal ON social_posts (source_signal_id, created_at DESC);
"""


def get_schema_sql() -> str:
    """Return the PostgreSQL schema DDL."""
    return SCHEMA_POSTGRES
