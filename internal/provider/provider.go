// Package provider defines a common interface over the Vietnamese market data
// sources (TCBS, VNDirect, SSI, ...). Add a new source by implementing Provider.
package provider

import (
	"context"
	"time"
)

// Bar is one daily OHLCV record, normalized to VND across all sources.
type Bar struct {
	Date   time.Time
	Open   float64
	High   float64
	Low    float64
	Close  float64
	Volume int64
}

// Symbol is a listed ticker.
type Symbol struct {
	Ticker   string
	Exchange string // HOSE, HNX, UPCOM
}

// Provider returns daily OHLCV for one ticker over [from, to], ascending by
// date, with prices in VND. Returning (nil, nil) means "no data" (e.g. the
// ticker is too old or delisted for this source) and is not an error.
type Provider interface {
	Name() string
	DailyHistory(ctx context.Context, ticker string, from, to time.Time) ([]Bar, error)
}
