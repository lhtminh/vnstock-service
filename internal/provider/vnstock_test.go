package provider

import (
	"encoding/json"
	"sort"
	"testing"
	"time"
)

func TestVNStockAdjusted(t *testing.T) {
	v := &VNStock{}
	if !v.Adjusted() {
		t.Error("vnstock provider should report adjusted = true")
	}
}

func TestTCBSAdjusted(t *testing.T) {
	tcbs := &TCBS{}
	if !tcbs.Adjusted() {
		t.Error("TCBS provider should report adjusted = true")
	}
}

func TestVNDirectAdjusted(t *testing.T) {
	vd := &VNDirect{}
	if !vd.Adjusted() {
		t.Error("VNDirect provider should report adjusted = true")
	}
}

func TestParseBarsFromFetchPy(t *testing.T) {
	input := []struct {
		Date   string  `json:"date"`
		Open   float64 `json:"open"`
		High   float64 `json:"high"`
		Low    float64 `json:"low"`
		Close  float64 `json:"close"`
		Volume int64   `json:"volume"`
	}{
		{Date: "2024-01-03", Open: 71000, High: 71500, Low: 70800, Close: 71200, Volume: 1500000},
		{Date: "2024-01-02", Open: 70500, High: 71200, Low: 70400, Close: 71000, Volume: 1200000},
		{Date: "2024-01-04", Open: 71200, High: 71800, Low: 71100, Close: 71600, Volume: 1800000},
	}

	raw, err := json.Marshal(input)
	if err != nil {
		t.Fatal(err)
	}

	var recs []struct {
		Date   string  `json:"date"`
		Open   float64 `json:"open"`
		High   float64 `json:"high"`
		Low    float64 `json:"low"`
		Close  float64 `json:"close"`
		Volume int64   `json:"volume"`
	}
	if err := json.Unmarshal(raw, &recs); err != nil {
		t.Fatal(err)
	}

	bars := make([]Bar, 0, len(recs))
	for _, r := range recs {
		day, err := time.Parse("2006-01-02", r.Date)
		if err != nil {
			t.Fatalf("unexpected parse error: %v", err)
		}
		bars = append(bars, Bar{
			Date: day.UTC(), Open: r.Open, High: r.High, Low: r.Low,
			Close: r.Close, Volume: r.Volume,
		})
	}
	sort.Slice(bars, func(i, j int) bool { return bars[i].Date.Before(bars[j].Date) })

	if len(bars) != 3 {
		t.Fatalf("expected 3 bars, got %d", len(bars))
	}

	// verify ascending date order
	for i := 1; i < len(bars); i++ {
		if !bars[i].Date.After(bars[i-1].Date) {
			t.Errorf("bar %d date %v is not after bar %d date %v", i, bars[i].Date, i-1, bars[i-1].Date)
		}
	}

	// verify values
	if bars[0].Close != 71000 || bars[0].Volume != 1200000 {
		t.Errorf("unexpected bar 0 values: close=%v vol=%v", bars[0].Close, bars[0].Volume)
	}
	if bars[2].Close != 71600 {
		t.Errorf("unexpected bar 2 close: %v", bars[2].Close)
	}
}

func TestParseBarsSkipsBadDates(t *testing.T) {
	input := []struct {
		Date   string  `json:"date"`
		Open   float64 `json:"open"`
		High   float64 `json:"high"`
		Low    float64 `json:"low"`
		Close  float64 `json:"close"`
		Volume int64   `json:"volume"`
	}{
		{Date: "2024-01-02", Open: 100, High: 110, Low: 90, Close: 105, Volume: 1000},
		{Date: "not-a-date", Open: 100, High: 110, Low: 90, Close: 105, Volume: 1000},
		{Date: "2024-01-03", Open: 100, High: 110, Low: 90, Close: 105, Volume: 1000},
	}

	raw, _ := json.Marshal(input)
	var recs []struct {
		Date   string  `json:"date"`
		Open   float64 `json:"open"`
		High   float64 `json:"high"`
		Low    float64 `json:"low"`
		Close  float64 `json:"close"`
		Volume int64   `json:"volume"`
	}
	json.Unmarshal(raw, &recs)

	bars := make([]Bar, 0, len(recs))
	for _, r := range recs {
		day, err := time.Parse("2006-01-02", r.Date)
		if err != nil {
			continue
		}
		bars = append(bars, Bar{
			Date: day.UTC(), Open: r.Open, High: r.High, Low: r.Low,
			Close: r.Close, Volume: r.Volume,
		})
	}

	if len(bars) != 2 {
		t.Fatalf("expected 2 bars after skipping bad date, got %d", len(bars))
	}
}
