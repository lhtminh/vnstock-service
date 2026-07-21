package provider

import (
	"context"
	"errors"
	"testing"
	"time"
)

type mockProvider struct {
	name     string
	adjusted bool
	bars     []Bar
	err      error
}

func (m *mockProvider) Name() string   { return m.name }
func (m *mockProvider) Adjusted() bool { return m.adjusted }
func (m *mockProvider) DailyHistory(_ context.Context, _ string, _, _ time.Time) ([]Bar, error) {
	return m.bars, m.err
}

func TestChainFallbackToNextProvider(t *testing.T) {
	p1 := &mockProvider{name: "dead", bars: nil, err: errors.New("timeout")}
	p2 := &mockProvider{name: "alive", bars: []Bar{{Date: time.Now(), Close: 100}}}

	c := NewChain(p1, p2)
	bars, source, err := c.DailyHistorySourced(context.Background(), "FPT", time.Now().AddDate(0, 0, -10), time.Now())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if source != "alive" {
		t.Fatalf("expected source 'alive', got %q", source)
	}
	if len(bars) != 1 {
		t.Fatalf("expected 1 bar, got %d", len(bars))
	}
}

func TestChainAllProvidersFail(t *testing.T) {
	p1 := &mockProvider{name: "a", err: errors.New("fail")}
	p2 := &mockProvider{name: "b", err: errors.New("fail")}

	c := NewChain(p1, p2)
	bars, source, err := c.DailyHistorySourced(context.Background(), "FPT", time.Now(), time.Now())
	if err == nil {
		t.Fatal("expected error when all providers fail")
	}
	if source != "" {
		t.Fatalf("expected empty source, got %q", source)
	}
	if bars != nil {
		t.Fatalf("expected nil bars, got %d", len(bars))
	}
}

func TestChainAllProvidersEmpty(t *testing.T) {
	p1 := &mockProvider{name: "a", bars: nil}
	p2 := &mockProvider{name: "b", bars: nil}

	c := NewChain(p1, p2)
	bars, source, err := c.DailyHistorySourced(context.Background(), "FPT", time.Now(), time.Now())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if source != "" {
		t.Fatalf("expected empty source, got %q", source)
	}
	if bars != nil {
		t.Fatalf("expected nil bars, got %d", len(bars))
	}
}

func TestChainProviderAdjusted(t *testing.T) {
	p1 := &mockProvider{name: "adjusted-raw", adjusted: false}
	p2 := &mockProvider{name: "adjusted-true", adjusted: true}
	p3 := &mockProvider{name: "another", adjusted: true}

	c := NewChain(p1, p2, p3)

	if c.ProviderAdjusted("adjusted-raw") {
		t.Error("expected adjusted=false for adjusted-raw")
	}
	if !c.ProviderAdjusted("adjusted-true") {
		t.Error("expected adjusted=true for adjusted-true")
	}
	if !c.ProviderAdjusted("unknown") {
		t.Error("expected adjusted=true for unknown provider (safe default)")
	}
}

func TestChainFirstNonEmptyWins(t *testing.T) {
	p1 := &mockProvider{name: "first", bars: []Bar{{Date: time.Now(), Close: 50}}}
	p2 := &mockProvider{name: "second", bars: []Bar{{Date: time.Now(), Close: 100}}}

	c := NewChain(p1, p2)
	_, source, err := c.DailyHistorySourced(context.Background(), "FPT", time.Now(), time.Now())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if source != "first" {
		t.Fatalf("expected source 'first', got %q", source)
	}
}
