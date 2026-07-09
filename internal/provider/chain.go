package provider

import (
	"context"
	"errors"
	"log"
	"time"
)

// Chain tries each provider in order and returns the first non-empty result.
// This is the resilience pattern: if the primary API changes format or
// rate-limits you, the next source fills in without changing calling code.
type Chain struct{ providers []Provider }

func NewChain(p ...Provider) *Chain { return &Chain{providers: p} }

func (c *Chain) Name() string { return "chain" }

func (c *Chain) DailyHistory(ctx context.Context, ticker string, from, to time.Time) ([]Bar, error) {
	var errs []error
	for _, p := range c.providers {
		bars, err := p.DailyHistory(ctx, ticker, from, to)
		if err != nil {
			errs = append(errs, err)
			log.Printf("provider %s failed for %s: %v", p.Name(), ticker, err)
			continue
		}
		if len(bars) > 0 {
			return bars, nil
		}
	}
	if len(errs) > 0 {
		return nil, errors.Join(errs...)
	}
	return nil, nil // no data anywhere — treat as empty, not an error
}
