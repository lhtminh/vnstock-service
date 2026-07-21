// Package provider defines a common interface over the Vietnamese market data
// sources (TCBS, VNDirect, SSI, ...). Add a new source by implementing Provider.
package provider

import (
	"context"
	"time"
)

// Bar is one daily OHLCV record for a single stock on a single trading day.
// OHLCV = Open, High, Low, Close, Volume — the classic candlestick fields.
// All prices are in VND (Vietnamese Dong), converted from whatever unit the
// source API uses. This normalization happens INSIDE each provider so the
// rest of the code never worries about unit mismatch.
type Bar struct {
	Date   time.Time
	Open   float64
	High   float64
	Low    float64
	Close  float64
	Volume int64
}

// Symbol is a single listed stock ticker on the Vietnamese market.
// Exchange is one of HOSE (Ho Chi Minh), HNX (Hanoi), or UPCOM (OTC).
type Symbol struct {
	Ticker   string
	Exchange string
}

// Provider is the core abstraction: any data source must implement this.
// This lets us plug in different sources (VCI, TCBS, VNDirect, SSI, ...)
// without changing the backfill/update commands. They all speak the same
// language: give me a ticker and a date range, get back []Bar in VND.
//
// Returning (nil, nil) means "no data" — the ticker might be too old or
// delisted — and is NOT treated as an error. An error means the source
// itself failed (timeout, rate-limit, etc.).
type Provider interface {
	Name() string
	DailyHistory(ctx context.Context, ticker string, from, to time.Time) ([]Bar, error)
	// Adjusted tells the store whether these prices are split/dividend-adjusted.
	// VCI returns adjusted prices (historical prices are recalculated to account
	// for stock splits and dividends). A raw feed like SSI would return false.
	// This matters because quant models need to know which kind of price they're
	// working with — you can't mix adjusted and raw in the same feature set.
	Adjusted() bool
}
