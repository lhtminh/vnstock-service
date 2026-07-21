// Package store persists symbols and daily prices in Postgres via pgx.
// pgx is the PostgreSQL driver for Go — think of it as a faster, modern
// alternative to database/sql with native Postgres features like COPY and batches.
package store

import (
	"context"
	_ "embed"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"vnstock-service/internal/provider"
)

//go:embed schema.sql
// schemaSQL is the raw SQL from schema.sql embedded into the Go binary at
// build time. The //go:embed directive tells Go to include the file's contents
// as a string. This means the binary carries its own schema — no separate
// migration files to manage.
var schemaSQL string

// Store wraps a Postgres connection pool. All database operations go through
// this struct. pgxpool manages connections efficiently (reuses them, limits
// how many are open at once).
type Store struct{ pool *pgxpool.Pool }

// Open connects to Postgres using a connection string (DSN).
// The DSN format: postgres://user:password@host:port/dbname?sslmode=disable
func Open(ctx context.Context, dsn string) (*Store, error) {
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return nil, err
	}
	return &Store{pool: pool}, nil
}

func (s *Store) Close() { s.pool.Close() }

// schemaVersion must be bumped whenever schema.sql changes structurally.
// EnsureSchema uses this to skip DDL on repeated startups, avoiding the
// ACCESS EXCLUSIVE locks that ALTER TABLE statements acquire.
const schemaVersion = 2

// StartBackfill records the start of a backfill run in the backfill_runs table.
// Returns a unique run ID that CompleteBackfill uses to mark the run as done.
// If a run has no completed_at, it means the process crashed mid-backfill —
// consumers can detect this and treat the data as potentially incomplete.
func (s *Store) StartBackfill(ctx context.Context, symbolCount int) (int64, error) {
	var id int64
	err := s.pool.QueryRow(ctx,
		`INSERT INTO backfill_runs (symbol_count) VALUES ($1) RETURNING id`, symbolCount).Scan(&id)
	return id, err
}

// CompleteBackfill marks a backfill run as finished with a bar count.
func (s *Store) CompleteBackfill(ctx context.Context, runID int64, barCount int64) error {
	_, err := s.pool.Exec(ctx,
		`UPDATE backfill_runs SET completed_at = now(), bar_count = $2 WHERE id = $1`, runID, barCount)
	return err
}

// EnsureSchema creates or migrates the database schema.
//
// Without caching: On every startup, schema.sql would run ALTER TABLE ... ADD
// COLUMN IF NOT EXISTS statements, which acquire ACCESS EXCLUSIVE locks that
// block ALL other queries. For a service that shares the DB with quant notebooks
// or other readers, this is disruptive.
//
// With caching: First, check _schema_version. If the stored version matches,
// skip the DDL entirely. Otherwise, run schema.sql (which is idempotent) and
// record the new version. This means schema DDL only runs once — on first
// deploy or after an upgrade.
func (s *Store) EnsureSchema(ctx context.Context) error {
	var v int
	err := s.pool.QueryRow(ctx, `SELECT version FROM _schema_version LIMIT 1`).Scan(&v)
	if err == nil && v >= schemaVersion {
		return nil
	}
	if _, err := s.pool.Exec(ctx, schemaSQL); err != nil {
		return err
	}
	_, err = s.pool.Exec(ctx,
		`INSERT INTO _schema_version (version) VALUES ($1)
		 ON CONFLICT (version) DO UPDATE SET applied_at = now()`, schemaVersion)
	return err
}

// UpsertSymbols inserts or updates a batch of symbols in one round-trip.
// pgx.Batch lets you send multiple SQL statements together, which is much
// faster than sending them one at a time (fewer network round-trips).
// ON CONFLICT DO UPDATE = "upsert": insert if new, update if exists.
func (s *Store) UpsertSymbols(ctx context.Context, syms []provider.Symbol) error {
	b := &pgx.Batch{}
	for _, sy := range syms {
		b.Queue(`INSERT INTO symbols (ticker, exchange) VALUES ($1, $2)
		         ON CONFLICT (ticker) DO UPDATE SET exchange = EXCLUDED.exchange, updated_at = now()`,
			sy.Ticker, sy.Exchange)
	}
	br := s.pool.SendBatch(ctx, b)
	for range syms {
		if _, err := br.Exec(); err != nil {
			br.Close()
			return err
		}
	}
	return br.Close()
}

// ListSymbols returns all known symbols from the database, ordered alphabetically.
// COALESCE handles NULL exchange values (converts them to empty string).
func (s *Store) ListSymbols(ctx context.Context) ([]provider.Symbol, error) {
	rows, err := s.pool.Query(ctx, `SELECT ticker, COALESCE(exchange, '') FROM symbols ORDER BY ticker`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []provider.Symbol
	for rows.Next() {
		var sy provider.Symbol
		if err := rows.Scan(&sy.Ticker, &sy.Exchange); err != nil {
			return nil, err
		}
		out = append(out, sy)
	}
	return out, rows.Err()
}

// LastDate returns the most recent stored trading date for a ticker.
// Used by the update command to know where to start fetching new data.
// Returns zero time if the ticker has no rows yet (new symbol, no history).
func (s *Store) LastDate(ctx context.Context, ticker string) (time.Time, error) {
	var d *time.Time
	err := s.pool.QueryRow(ctx,
		`SELECT max(date) FROM daily_prices WHERE ticker = $1`, ticker).Scan(&d)
	if err != nil {
		return time.Time{}, err
	}
	if d == nil {
		return time.Time{}, nil
	}
	return *d, nil
}

// UpsertBars writes OHLCV bars into daily_prices in batches of 500.
// "Upsert" = INSERT ... ON CONFLICT DO UPDATE — if a row for (ticker, date)
// already exists, update it. This makes the operation idempotent: running
// the backfill twice produces the same result as running it once.
//
// isAdjusted tells the database whether these are adjusted or raw prices.
// source records which provider served the data (e.g. "vnstock", "ssi").
func (s *Store) UpsertBars(ctx context.Context, ticker, source string, isAdjusted bool, bars []provider.Bar) error {
	const batchSize = 500
	for i := 0; i < len(bars); i += batchSize {
		end := i + batchSize
		if end > len(bars) {
			end = len(bars)
		}
		b := &pgx.Batch{}
		for _, bar := range bars[i:end] {
			b.Queue(`INSERT INTO daily_prices (ticker, date, open, high, low, close, volume, is_adjusted, source)
			         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
			         ON CONFLICT (ticker, date) DO UPDATE SET
			           open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
			           close = EXCLUDED.close, volume = EXCLUDED.volume,
			           is_adjusted = EXCLUDED.is_adjusted, source = EXCLUDED.source`,
				ticker, bar.Date, bar.Open, bar.High, bar.Low, bar.Close, bar.Volume, isAdjusted, source)
		}
		br := s.pool.SendBatch(ctx, b)
		for j := i; j < end; j++ {
			if _, err := br.Exec(); err != nil {
				br.Close()
				return err
			}
		}
		if err := br.Close(); err != nil {
			return err
		}
	}
	return nil
}
