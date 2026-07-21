package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/url"
	"time"

	"vnstock-service/internal/httpx"
)

// VNDirect reads the public finfo REST API. Confirmed query shape:
//
//	https://finfo-api.vndirect.com.vn/v4/stock_prices/?sort=date&size=1000&page=1&q=code:FPT~date:gte:2005-01-01~date:lte:2025-01-01
//
// VERIFY UNITS ONCE: depending on the field, finfo may return prices in
// thousands of VND. Check a known day against a chart and set vndPriceScale.
type VNDirect struct{ http *httpx.Client }

func NewVNDirect(c *httpx.Client) *VNDirect { return &VNDirect{http: c} }

func (v *VNDirect) Name() string   { return "vndirect" }
func (v *VNDirect) Adjusted() bool { return true }

// If finfo already returns VND keep 1.0; if it returns thousands, set 1000.
const vndPriceScale = 1.0

const (
	vndPricesBase = "https://finfo-api.vndirect.com.vn/v4/stock_prices/"
	vndStocksBase = "https://finfo-api.vndirect.com.vn/v4/stocks"
)

type vndPricesResp struct {
	CurrentPage int `json:"currentPage"`
	TotalPages  int `json:"totalPages"`
	Data        []struct {
		Date   string  `json:"date"` // "2021-01-04"
		Open   float64 `json:"open"`
		High   float64 `json:"high"`
		Low    float64 `json:"low"`
		Close  float64 `json:"close"`
		Volume float64 `json:"nmVolume"`
	} `json:"data"`
}

func (v *VNDirect) DailyHistory(ctx context.Context, ticker string, from, to time.Time) ([]Bar, error) {
	q := fmt.Sprintf("code:%s~date:gte:%s~date:lte:%s",
		ticker, from.Format("2006-01-02"), to.Format("2006-01-02"))
	seen := make(map[string]Bar)
	page := 1
	for {
		u := fmt.Sprintf("%s?sort=date&size=1000&page=%d&q=%s", vndPricesBase, page, url.QueryEscape(q))
		body, err := v.http.Get(ctx, u)
		if err != nil {
			return nil, fmt.Errorf("vndirect %s: %w", ticker, err)
		}
		var r vndPricesResp
		if err := json.Unmarshal(body, &r); err != nil {
			return nil, fmt.Errorf("vndirect %s decode: %w", ticker, err)
		}
		for _, d := range r.Data {
			day, err := time.Parse("2006-01-02", d.Date)
			if err != nil {
				log.Printf("vndirect %s: skipping bar with unparseable date %q: %v", ticker, d.Date, err)
				continue
			}
			seen[d.Date] = Bar{
				Date:   day.UTC(),
				Open:   d.Open * vndPriceScale,
				High:   d.High * vndPriceScale,
				Low:    d.Low * vndPriceScale,
				Close:  d.Close * vndPriceScale,
				Volume: int64(d.Volume),
			}
		}
		if len(r.Data) == 0 || r.CurrentPage >= r.TotalPages {
			break
		}
		page++
	}
	return sortedBars(seen), nil
}

type vndStocksResp struct {
	Data []struct {
		Code  string `json:"code"`
		Floor string `json:"floor"` // HOSE / HNX / UPCOM
		Type  string `json:"type"`
	} `json:"data"`
}

// ListSymbols pulls the listed-stock universe (~1600-1700 tickers) so you don't
// have to maintain a seed file by hand. VERIFY the endpoint once with curl.
func (v *VNDirect) ListSymbols(ctx context.Context) ([]Symbol, error) {
	q := url.QueryEscape("type:STOCK~status:LISTED")
	u := fmt.Sprintf("%s?q=%s&size=3000", vndStocksBase, q)
	body, err := v.http.Get(ctx, u)
	if err != nil {
		return nil, err
	}
	var r vndStocksResp
	if err := json.Unmarshal(body, &r); err != nil {
		return nil, err
	}
	out := make([]Symbol, 0, len(r.Data))
	for _, d := range r.Data {
		out = append(out, Symbol{Ticker: d.Code, Exchange: d.Floor})
	}
	return out, nil
}
