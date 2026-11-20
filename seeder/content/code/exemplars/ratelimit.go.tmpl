// Package ratelimit provides a token-bucket rate limiter and HTTP middleware built on it.
package ratelimit

import (
	"net"
	"net/http"
	"strconv"
	"sync"
	"time"
)

// Bucket holds tokens that refill at a steady rate up to a fixed capacity.
type Bucket struct {
	mu       sync.Mutex
	capacity float64
	tokens   float64
	rate     float64
	updated  time.Time
}

// NewBucket returns a full bucket that refills at rate tokens per second.
func NewBucket(capacity int, rate float64) *Bucket {
	return &Bucket{
		capacity: float64(capacity),
		tokens:   float64(capacity),
		rate:     rate,
		updated:  time.Now(),
	}
}

func (b *Bucket) refill(now time.Time) {
	elapsed := now.Sub(b.updated).Seconds()
	b.tokens += elapsed * b.rate
	if b.tokens > b.capacity {
		b.tokens = b.capacity
	}
	b.updated = now
}

// Allow takes one token if one is available and reports whether it did.
func (b *Bucket) Allow() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.refill(time.Now())
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}

// RetryAfter is how long a caller should wait for the next token.
func (b *Bucket) RetryAfter() time.Duration {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.refill(time.Now())
	if b.tokens >= 1 {
		return 0
	}
	return time.Duration((1 - b.tokens) / b.rate * float64(time.Second))
}

// Limiter keeps one bucket per client key and forgets idle clients.
type Limiter struct {
	mu       sync.Mutex
	buckets  map[string]*Bucket
	capacity int
	rate     float64
	idle     time.Duration
}

// NewLimiter starts a limiter and a goroutine that removes idle buckets.
func NewLimiter(capacity int, rate float64, idle time.Duration) *Limiter {
	limiter := &Limiter{buckets: map[string]*Bucket{}, capacity: capacity, rate: rate, idle: idle}
	go limiter.sweep()
	return limiter
}

func (l *Limiter) bucket(key string) *Bucket {
	l.mu.Lock()
	defer l.mu.Unlock()
	bucket, ok := l.buckets[key]
	if !ok {
		bucket = NewBucket(l.capacity, l.rate)
		l.buckets[key] = bucket
	}
	return bucket
}

func (l *Limiter) sweep() {
	for range time.Tick(l.idle) {
		l.mu.Lock()
		for key, bucket := range l.buckets {
			if time.Since(bucket.updated) > l.idle {
				delete(l.buckets, key)
			}
		}
		l.mu.Unlock()
	}
}

// Middleware rejects requests over the limit with status 429 and a Retry-After header.
func (l *Limiter) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host, _, err := net.SplitHostPort(r.RemoteAddr)
		if err != nil {
			host = r.RemoteAddr
		}
		bucket := l.bucket(host)
		if !bucket.Allow() {
			seconds := int(bucket.RetryAfter().Seconds()) + 1
			w.Header().Set("Retry-After", strconv.Itoa(seconds))
			http.Error(w, "too many requests", http.StatusTooManyRequests)
			return
		}
		next.ServeHTTP(w, r)
	})
}
