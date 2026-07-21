package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"sort"
	"time"

	"vnstock-service/internal/httpx"
)

// TCBS reads the public "bars-long-term" endpoint. Prices come back already in
// VND and history is reasonably deep, so this is the recommended primary source.
//
// Verify once before trusting it:
//
//	curl 'https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/bars-long-term?ticker=FPT&type=stock&resolution=D&to=1720000000&countBack=100'
type TCBS struct{ http *httpx.Client }

func NewTCBS(c *httpx.Client) *TCBS { return &TCBS{http: c} }

func (t *TCBS) Name() string   { return "tcbs" }
func (t *TCBS) Adjusted() bool { return true }

const tcbsBase = "https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/bars-long-term"

type tcbsResp struct {
	Data []struct {
		Open        float64 `json:"open"`
		High        float64 `json:"high"`
		Low         float64 `json:"low"`
		Close       float64 `json:"close"`
		Volume      int64   `json:"volume"`
		TradingDate string  `json:"tradingDate"` // RFC3339, e.g. "2021-01-04T00:00:00.000Z"
	} `json:"data"`
}

func (t *TCBS) DailyHistory(ctx context.Context, ticker string, from, to time.Time) ([]Bar, error) {
	const chunk = 1000 // bars per request; we page backwards until we pass `from`.
	seen := make(map[string]Bar)
	cursor := to
	for {
		url := fmt.Sprintf("%s?ticker=%s&type=stock&resolution=D&to=%d&countBack=%d",
			tcbsBase, ticker, cursor.Unix(), chunk)
		body, err := t.http.Get(ctx, url)
		if err != nil {
			return nil, fmt.Errorf("tcbs %s: %w", ticker, err)
		}
		var r tcbsResp
		if err := json.Unmarshal(body, &r); err != nil {
			return nil, fmt.Errorf("tcbs %s decode: %w", ticker, err)
		}
		if len(r.Data) == 0 {
			break
		}
		var earliest time.Time
		for _, d := range r.Data {
			ts, err := time.Parse(time.RFC3339, d.TradingDate)
			if err != nil {
				log.Printf("tcbs %s: skipping bar with unparseable date %q: %v", ticker, d.TradingDate, err)
				continue
			}
			day := ts.UTC().Truncate(24 * time.Hour)
			if earliest.IsZero() || day.Before(earliest) {
				earliest = day
			}
			if day.Before(from) || day.After(to) {
				continue
			}
			seen[day.Format("2006-01-02")] = Bar{
				Date: day, Open: d.Open, High: d.High, Low: d.Low,
				Close: d.Close, Volume: d.Volume,
			}
		}
		// Stop when we've reached back past `from`, the source ran out, or the
		// cursor can't advance (guards against an infinite loop).
		if earliest.IsZero() || !earliest.After(from) || len(r.Data) < chunk {
			break
		}
		next := earliest.AddDate(0, 0, -1)
		if !next.Before(cursor) {
			break
		}
		cursor = next
	}
	return sortedBars(seen), nil
}

func sortedBars(m map[string]Bar) []Bar {
	out := make([]Bar, 0, len(m))
	for _, b := range m {
		out = append(out, b)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Date.Before(out[j].Date) })
	return out
}
