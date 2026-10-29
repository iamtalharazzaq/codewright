// Command api serves the {{title}} backend.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"{{name}}/internal/api"
	"{{name}}/internal/store"
)

func main() {
	ctx := context.Background()
	var s store.Store = store.NewMemory() // no DATABASE_URL: in memory, handy for trying it out
	if url := os.Getenv("DATABASE_URL"); url != "" {
		pg, err := store.OpenPostgres(ctx, url)
		if err != nil {
			slog.Error("cannot open the database", "err", err)
			os.Exit(1)
		}
		defer pg.Close()
		s = pg
	}
	secret := os.Getenv("SECRET_KEY")
	if secret == "" {
		slog.Warn("SECRET_KEY is not set: using an insecure development secret")
		secret = "dev-secret-change-me"
	}

	addr := ":" + envOr("PORT", "{{port}}")
	srv := &http.Server{Addr: addr, Handler: api.New(s, secret), ReadHeaderTimeout: 5 * time.Second}
	go func() {
		slog.Info("listening", "addr", addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			slog.Error("server stopped", "err", err)
			os.Exit(1)
		}
	}()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	shutdown, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdown)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
