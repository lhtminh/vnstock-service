-- vnstock-service schema (v2 — quant-modeling ready)
--
-- This file is IDEMPOTENT and additive: run it on a fresh database to create
-- everything, or on the v1 database to upgrade in place. New columns on
-- pre-existing tables are added via ALTER ... ADD COLUMN IF NOT EXISTS, so
-- existing rows keep their data and simply carry NULLs for the new fields until
-- re-fetched.
--
-- Design principles baked in here:
--   1. Survivorship: delisted tickers are KEPT (symbols.status), never purged.
--   2. Point-in-time: fundamentals and index membership record WHEN a fact
--      became knowable, so features can be built without look-ahead.
--   3. Reproducible adjustment: raw prices are immutable; corporate actions are
--      stored as events and applied at feature time (no mutating adj_close).
--   4. Data quality: price-limit bands + a per-bar status flag distinguish a
--      real tradeable price from a limit-locked / halted / no-trade bar.

-- ---------------------------------------------------------------------------
-- symbols: the ticker universe, including delisted names (survivorship-safe)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS symbols (
    ticker        TEXT PRIMARY KEY,
    exchange      TEXT,                    -- current/last exchange: HOSE/HNX/UPCOM
    company_name  TEXT,
    icb_code      TEXT,                    -- industry classification (sector/industry)
    status        TEXT DEFAULT 'active',   -- active / delisted / suspended
    listed_date   DATE,
    delisted_date DATE,
    isin          TEXT,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- upgrade path for a v1 symbols table:
ALTER TABLE symbols ADD COLUMN IF NOT EXISTS company_name  TEXT;
ALTER TABLE symbols ADD COLUMN IF NOT EXISTS icb_code      TEXT;
ALTER TABLE symbols ADD COLUMN IF NOT EXISTS status        TEXT DEFAULT 'active';
ALTER TABLE symbols ADD COLUMN IF NOT EXISTS listed_date   DATE;
ALTER TABLE symbols ADD COLUMN IF NOT EXISTS delisted_date DATE;
ALTER TABLE symbols ADD COLUMN IF NOT EXISTS isin          TEXT;
ALTER TABLE symbols ADD COLUMN IF NOT EXISTS updated_at    TIMESTAMPTZ NOT NULL DEFAULT now();

-- ---------------------------------------------------------------------------
-- trading_calendar: lets you tell "market closed" from "missing" from "halted"
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trading_calendar (
    date            DATE PRIMARY KEY,
    is_trading_day  BOOLEAN NOT NULL,
    note            TEXT                     -- e.g. "Tet holiday", "special session"
);

-- ---------------------------------------------------------------------------
-- daily_prices: raw traded OHLCV in VND (NEVER adjusted in place) + liquidity
-- and quality context. Adjusted series are derived at feature time.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker         TEXT NOT NULL,
    date           DATE NOT NULL,
    open           NUMERIC(18, 2),
    high           NUMERIC(18, 2),
    low            NUMERIC(18, 2),
    close          NUMERIC(18, 2),
    volume         BIGINT,                  -- matched (khop lenh) volume, shares
    value          BIGINT,                  -- matched value, VND (liquidity signal)
    deal_volume    BIGINT,                  -- put-through (thoa thuan) volume
    deal_value     BIGINT,                  -- put-through value, VND
    ref_price      NUMERIC(18, 2),          -- reference price for the session
    ceiling_price  NUMERIC(18, 2),          -- price-limit band (HOSE +7% etc.)
    floor_price    NUMERIC(18, 2),
    bar_status     TEXT,                    -- normal/limit_up/limit_down/halted/no_trade/unknown
    is_adjusted    BOOLEAN NOT NULL DEFAULT true,  -- VCI feed is split/dividend-ADJUSTED; a true raw feed (e.g. SSI) would set false
    source         TEXT,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, date)
);
-- upgrade path for a v1 daily_prices table:
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS value         BIGINT;
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS deal_volume   BIGINT;
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS deal_value    BIGINT;
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS ref_price     NUMERIC(18, 2);
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS ceiling_price NUMERIC(18, 2);
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS floor_price   NUMERIC(18, 2);
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS bar_status    TEXT;
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS is_adjusted   BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices (date);

-- ---------------------------------------------------------------------------
-- corporate_actions: the source of truth for price adjustment. Store events;
-- compute split/dividend-adjusted series on read. Never mutate daily_prices.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS corporate_actions (
    id           BIGSERIAL PRIMARY KEY,
    ticker       TEXT NOT NULL,
    action_type  TEXT NOT NULL,            -- cash_dividend/stock_dividend/stock_split/rights_issue/bonus
    ex_date      DATE NOT NULL,            -- the date the price adjusts
    record_date  DATE,
    pay_date     DATE,
    cash_amount  NUMERIC(18, 2),           -- VND per share, for cash dividends
    ratio_from   NUMERIC(18, 6),           -- for splits/stock dividends: from:to
    ratio_to     NUMERIC(18, 6),
    note         TEXT,
    source       TEXT,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ticker, action_type, ex_date)
);
CREATE INDEX IF NOT EXISTS idx_corp_actions_ticker_ex ON corporate_actions (ticker, ex_date);

-- ---------------------------------------------------------------------------
-- foreign_flows: foreign investor (khoi ngoai) + proprietary (tu doanh) flows.
-- Among the most predictive behavioural signals in the VN market.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS foreign_flows (
    ticker              TEXT NOT NULL,
    date                DATE NOT NULL,
    foreign_buy_volume  BIGINT,
    foreign_buy_value   BIGINT,            -- VND
    foreign_sell_volume BIGINT,
    foreign_sell_value  BIGINT,            -- VND
    foreign_net_value   BIGINT,            -- VND, signed (buy - sell)
    foreign_room        BIGINT,            -- remaining foreign ownership room, shares
    prop_net_value      BIGINT,            -- tu doanh net, VND, signed (nullable)
    source              TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_foreign_flows_date ON foreign_flows (date);

-- ---------------------------------------------------------------------------
-- financial_statements: point-in-time fundamentals in long format.
-- publish_date is the anti-look-ahead key: "what was knowable as of date D"
-- = rows WHERE publish_date <= D. Long format survives source/line-item churn.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS financial_statements (
    ticker          TEXT NOT NULL,
    statement_type  TEXT NOT NULL,         -- balance_sheet / income_statement / cash_flow / ratios
    period_type     TEXT NOT NULL,         -- quarter / year
    period_end      DATE NOT NULL,         -- fiscal period end (e.g. 2023-06-30)
    publish_date    DATE,                  -- when it became public (POINT-IN-TIME KEY)
    item_code       TEXT NOT NULL,         -- e.g. "net_revenue", "net_income", "total_assets"
    value           NUMERIC(24, 4),
    unit            TEXT,                  -- VND, %, ratio, ...
    source          TEXT,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, statement_type, period_type, period_end, item_code)
);
CREATE INDEX IF NOT EXISTS idx_fin_stmt_pit ON financial_statements (ticker, publish_date);

-- ---------------------------------------------------------------------------
-- index_series: benchmark levels (VNINDEX, VN30, HNX, ...) for excess return,
-- beta, and market-state features.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS index_series (
    index_code  TEXT NOT NULL,             -- VNINDEX / VN30 / HNXINDEX / HNX30 / UPCOMINDEX
    date        DATE NOT NULL,
    open        NUMERIC(12, 2),
    high        NUMERIC(12, 2),
    low         NUMERIC(12, 2),
    close       NUMERIC(12, 2),
    volume      BIGINT,
    value       BIGINT,                    -- VND
    source      TEXT,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, date)
);
CREATE INDEX IF NOT EXISTS idx_index_series_date ON index_series (date);

-- ---------------------------------------------------------------------------
-- index_membership: point-in-time constituents (VN30 reconstitutes twice a
-- year). Prevents look-ahead in universe selection: "who was in VN30 on D"
-- = rows WHERE effective_date <= D AND (end_date IS NULL OR end_date > D).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS index_membership (
    index_code     TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    effective_date DATE NOT NULL,          -- entered the index on
    end_date       DATE,                   -- left the index on (NULL = still in)
    weight         NUMERIC(9, 6),          -- optional constituent weight
    source         TEXT,
    PRIMARY KEY (index_code, ticker, effective_date)
);
CREATE INDEX IF NOT EXISTS idx_index_membership_asof ON index_membership (index_code, effective_date, end_date);

-- ---------------------------------------------------------------------------
-- backfill_runs: tracks backfill runs so consumers can detect a partial dataset
-- caused by a crash mid-backfill. A row with completed_at IS NULL means the
-- run was interrupted — treat data from that run as suspect.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backfill_runs (
    id             BIGSERIAL PRIMARY KEY,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at   TIMESTAMPTZ,
    symbol_count   INT,
    bar_count      BIGINT,
    worker_count   INT
);

-- ---------------------------------------------------------------------------
-- _schema_version: tracks applied schema version so EnsureSchema can skip DDL
-- on repeated startups, avoiding unnecessary ACCESS EXCLUSIVE locks.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS _schema_version (
    version     INT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
