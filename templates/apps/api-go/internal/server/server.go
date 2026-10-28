// Package server wires the routes and middleware.
package server

import (
	"log/slog"
	"net/http"
	"time"

	"{{name}}/internal/items"
)

// New returns the API's handler.
func New(store items.Store) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(index))
	})
	items.Register(mux, store)
	return logRequests(mux)
}

func logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		slog.Info("request", "method", r.Method, "path", r.URL.Path, "took", time.Since(start))
	})
}

const index = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{{title}}</title>
<style>:root{color-scheme:light dark;font-family:system-ui,sans-serif}body{max-width:40rem;margin:3rem auto;padding:0 1rem}
code{background:color-mix(in oklab,currentColor 10%,transparent);padding:.1rem .3rem;border-radius:.3rem}</style>
<h1>{{title}}</h1><p>{{description}}</p>
<ul><li><a href="/health"><code>GET /health</code></a></li><li><a href="/api/items"><code>GET /api/items</code></a></li>
<li><code>POST /api/items {"name": "…"}</code></li><li><code>PUT /api/items/{id}</code>, <code>DELETE /api/items/{id}</code></li></ul>`
