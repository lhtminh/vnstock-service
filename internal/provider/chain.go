package provider

import (
	"context"
	"errors"
	"log"
	"time"
)

// Chain tries each provider in order and returns the first non-empty result.
// Think of it as a fallback chain: if the primary source fails (e.g. VCI is
// rate-limiting), we try the next one. This makes the system resilient to
// individual API failures without any retry logic in the calling code.
//
// Currently the chain only has one provider (vnstock) because TCBS and VNDirect
// are dead. When they recover, just add them back to NewChain() and the chain
// will try them automatically.
type Chain struct{ providers []Provider }

func NewChain(p ...Provider) *Chain { return &Chain{providers: p} }

func (c *Chain) Name() string { return "chain" }

func (c *Chain) DailyHistory(ctx context.Context, ticker string, from, to time.Time) ([]Bar, error) {
	bars, _, err := c.DailyHistorySourced(ctx, ticker, from, to)
	return bars, err
}

// DailyHistorySourced is like DailyHistory but also reports the Name() of the
// provider that actually served the data. This is important because we store
// the source name alongside each bar in the database. If the chain falls back
// to TCBS for one ticker and vnstock for another, we want to know which is
// which — especially for the is_adjusted flag.
//
// The chain works like a priority list:
//   - Provider 1 (vnstock): usually returns data quickly — use it.
//   - Provider 2 (TCBS): only tried if provider 1 errors.
//   - Provider 3 (VNDirect): last resort.
//   - If all error: return all errors joined together.
//   - If all return empty but no errors: return (nil, "", nil) — means
//     "this ticker genuinely has no data from any source, which is fine."
func (c *Chain) DailyHistorySourced(ctx context.Context, ticker string, from, to time.Time) ([]Bar, string, error) {
	var errs []error
	for _, p := range c.providers {
		bars, err := p.DailyHistory(ctx, ticker, from, to)
		if err != nil {
			errs = append(errs, err)
			log.Printf("provider %s failed for %s: %v", p.Name(), ticker, err)
			continue
		}
		if len(bars) > 0 {
			return bars, p.Name(), nil
		}
	}
	if len(errs) > 0 {
		return nil, "", errors.Join(errs...)
	}
	return nil, "", nil // no data anywhere — treat as empty, not an error
}

// ProviderAdjusted looks up which provider served the data (by name) and asks
// it whether its prices are adjusted. This replaces the old hardcoded
// `source != "ssi"` check — now each provider owns its own answer.
// If the source isn't found in the chain (shouldn't happen), default to true
// as a safe conservative choice.
func (c *Chain) ProviderAdjusted(source string) bool {
	for _, p := range c.providers {
		if p.Name() == source {
			return p.Adjusted()
		}
	}
	return true
}
