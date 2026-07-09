// Package store persists symbols and daily prices in Postgres via pgx.
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
var schemaSQL string

type Store struct{ pool *pgxpool.Pool }

func Open(ctx context.Context, dsn string) (*Store, error) {
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return nil, err
	}
	return &Store{pool: pool}, nil
}

func (s *Store) Close() { s.pool.Close() }

func (s *Store) EnsureSchema(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, schemaSQL)
	return err
}

func (s *Store) UpsertSymbols(ctx context.Context, syms []provider.Symbol) error {
	b := &pgx.Batch{}
	for _, sy := range syms {
		b.Queue(`INSERT INTO symbols (ticker, exchange) VALUES ($1, $2)
		         ON CONFLICT (ticker) DO UPDATE SET exchange = EXCLUDED.exchange`,
			sy.Ticker, sy.Exchange)
	}
	br := s.pool.SendBatch(ctx, b)
	defer br.Close()
	for range syms {
		if _, err := br.Exec(); err != nil {
			return err
		}
	}
	return nil
}

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

// LastDate returns the most recent stored date for a ticker, or zero time if
// the ticker has no rows yet.
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

// UpsertBars writes bars in batches, overwriting rows that already exist so
// re-running the backfill (or overlapping the daily update) is idempotent.
func (s *Store) UpsertBars(ctx context.Context, ticker, source string, bars []provider.Bar) error {
	const batchSize = 500
	for i := 0; i < len(bars); i += batchSize {
		end := i + batchSize
		if end > len(bars) {
			end = len(bars)
		}
		b := &pgx.Batch{}
		for _, bar := range bars[i:end] {
			b.Queue(`INSERT INTO daily_prices (ticker, date, open, high, low, close, volume, source)
			         VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
			         ON CONFLICT (ticker, date) DO UPDATE SET
			           open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
			           close = EXCLUDED.close, volume = EXCLUDED.volume, source = EXCLUDED.source`,
				ticker, bar.Date, bar.Open, bar.High, bar.Low, bar.Close, bar.Volume, source)
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
