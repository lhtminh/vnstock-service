// Package httpx provides a shared HTTP client with a global rate limiter and
// retry-with-backoff. The Vietnamese broker APIs throttle by IP, so ALL
// providers and workers must share ONE *Client instance.
package httpx

import (
	"context"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"time"
)

type Client struct {
	hc      *http.Client
	limiter *limiter
	retries int
}

// New builds a client limited to reqPerSec requests/second across all callers,
// retrying up to `retries` times on 429/5xx/network errors.
func New(reqPerSec, retries int) *Client {
	return &Client{
		hc:      &http.Client{Timeout: 30 * time.Second},
		limiter: newLimiter(reqPerSec),
		retries: retries,
	}
}

// Get fetches url and returns the raw body, respecting the rate limit and
// retrying transient failures.
func (c *Client) Get(ctx context.Context, url string) ([]byte, error) {
	var lastErr error
	for attempt := 0; attempt <= c.retries; attempt++ {
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
		case resp.StatusCode == http.StatusOK:
			return body, nil
		case resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500:
			lastErr = &HTTPError{Status: resp.StatusCode, Body: string(body)}
			backoff(ctx, attempt)
			continue
		default:
			return nil, &HTTPError{Status: resp.StatusCode, Body: string(body)}
		}
	}
	return nil, lastErr
}

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

// limiter is a token bucket refilled by a ticker.
type limiter struct{ tokens chan struct{} }

func newLimiter(reqPerSec int) *limiter {
	if reqPerSec < 1 {
		reqPerSec = 1
	}
	l := &limiter{tokens: make(chan struct{}, reqPerSec)}
	for i := 0; i < reqPerSec; i++ {
		l.tokens <- struct{}{}
	}
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

func (l *limiter) wait(ctx context.Context) error {
	select {
	case <-l.tokens:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func backoff(ctx context.Context, attempt int) {
	d := time.Duration(1<<attempt) * 300 * time.Millisecond
	if d > 10*time.Second {
		d = 10 * time.Second
	}
	d += time.Duration(rand.Int63n(int64(200 * time.Millisecond)))
	select {
	case <-time.After(d):
	case <-ctx.Done():
	}
}
