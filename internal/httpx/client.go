// Package httpx provides a shared HTTP client with rate limiting and retry
// with exponential backoff. The Vietnamese broker APIs throttle by IP, so if
// you use HTTP sources, ALL workers should share ONE *Client instance.
//
// IMPORTANT: This package is currently UNUSED because TCBS and VNDirect are
// dead. It's kept for when they (or a future HTTP source like SSI) come back.
// To use it, pass the client to the provider's constructor, e.g.:
//
//	client := httpx.New(rps, retries)
//	src := provider.NewChain(
//	    vnstk,
//	    provider.NewTCBS(client),   // would use httpx
//	)
package httpx

import (
	"context"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"time"
)

// Client wraps http.Client with a token-bucket rate limiter and retry logic.
// All fields are unexported — you interact only through New() and Get().
type Client struct {
	hc      *http.Client
	limiter *limiter
	retries int // max retries for 429/5xx/network errors
}

// New creates a Client that allows reqPerSec requests per second across all
// goroutines combined, retrying up to retries times on transient failures.
//
// The rate limiter is a token bucket (see newLimiter). The retry uses
// exponential backoff: 300ms, 600ms, 1.2s, ... capped at 10s + jitter.
func New(reqPerSec, retries int) *Client {
	return &Client{
		hc:      &http.Client{Timeout: 30 * time.Second},
		limiter: newLimiter(reqPerSec),
		retries: retries,
	}
}

// Get performs a GET request with rate limiting and automatic retries.
//
// Retry logic:
//   - Success (2xx): return body immediately.
//   - 429 Too Many Requests or 5xx: log the error, backoff, retry.
//   - Other status codes: return immediately as an error (no retry — 4xx
//     errors like 400 Bad Request won't become 200 by retrying).
//   - Network error: backoff, retry.
//
// The ctx parameter is passed to the underlying HTTP request AND to the
// rate limiter. Cancel the context to abort a stuck request.
func (c *Client) Get(ctx context.Context, url string) ([]byte, error) {
	var lastErr error
	for attempt := 0; attempt < c.retries; attempt++ {
		// Block until we have a rate-limit token or the context is cancelled.
		if err := c.limiter.wait(ctx); err != nil {
			return nil, err
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		if err != nil {
			return nil, err
		}
		// A browser-like UA avoids naive bot blocks on these public endpoints.
		req.Header.Set("User-Agent", "Mozilla/5.0 (compatible; vnstock-service/1.0)")
		req.Header.Set("Accept", "application/json")

		resp, err := c.hc.Do(req)
		if err != nil {
			lastErr = err
			backoff(ctx, attempt)
			continue
		}
		body, readErr := io.ReadAll(resp.Body)
		resp.Body.Close()
		if readErr != nil {
			lastErr = readErr
			backoff(ctx, attempt)
			continue
		}
		switch {
		case resp.StatusCode >= 200 && resp.StatusCode < 300:
			return body, nil
		case resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500:
			lastErr = &HTTPError{Status: resp.StatusCode, Body: string(body)}
			backoff(ctx, attempt)
			continue
		default:
			// 4xx errors: don't retry (the request itself is wrong).
			return nil, &HTTPError{Status: resp.StatusCode, Body: string(body)}
		}
	}
	return nil, lastErr
}

// HTTPError represents a non-success HTTP response with a truncated body.
type HTTPError struct {
	Status int
	Body   string
}

func (e *HTTPError) Error() string {
	b := e.Body
	if len(b) > 200 {
		b = b[:200]
	}
	return fmt.Sprintf("http %d: %s", e.Status, b)
}

// limiter implements a token bucket rate limiter using a buffered channel.
// Each "token" is an empty struct{} (zero memory). The channel starts full
// (reqPerSec tokens), and a ticker adds one token per [second/reqPerSec].
//
// Think of it like a jar of marbles: you start with N marbles. Every time
// you make a request, you take a marble. Every 1/N seconds, a new marble
// is added. If the jar is empty, you wait until a marble appears.
type limiter struct{ tokens chan struct{} }

func newLimiter(reqPerSec int) *limiter {
	if reqPerSec < 1 {
		reqPerSec = 1
	}
	// Buffered channel = the jar. Capacity = max burst size.
	l := &limiter{tokens: make(chan struct{}, reqPerSec)}
	// Fill the jar initially.
	for i := 0; i < reqPerSec; i++ {
		l.tokens <- struct{}{}
	}
	// Background goroutine: add one token every (1/reqPerSec) seconds.
	// The default case prevents the channel from overflowing.
	go func() {
		t := time.NewTicker(time.Second / time.Duration(reqPerSec))
		defer t.Stop()
		for range t.C {
			select {
			case l.tokens <- struct{}{}:
			default:
			}
		}
	}()
	return l
}

// wait blocks until a token is available or the context is cancelled.
func (l *limiter) wait(ctx context.Context) error {
	select {
	case <-l.tokens:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// backoff sleeps for an exponentially increasing duration, with jitter.
//   - attempt=0: 300ms
//   - attempt=1: 600ms
//   - attempt=2: 1.2s
//   - attempt=3: 2.4s
//   - ...
//   - Capped at 10s, plus random jitter of up to 200ms.
//
// Using time.NewTimer + defer t.Stop() instead of time.After ensures the
// timer is cleaned up if the context is cancelled (time.After leaks timers
// until they fire, which wastes memory under high cancellation rates).
func backoff(ctx context.Context, attempt int) {
	d := time.Duration(1<<attempt) * 300 * time.Millisecond
	if d > 10*time.Second {
		d = 10 * time.Second
	}
	d += time.Duration(rand.Int63n(int64(200 * time.Millisecond)))
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-t.C:
	case <-ctx.Done():
	}
}
