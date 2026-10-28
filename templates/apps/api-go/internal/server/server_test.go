package server

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"{{name}}/internal/items"
)

func TestHealth(t *testing.T) {
	rec := httptest.NewRecorder()
	New(items.NewMemoryStore()).ServeHTTP(rec, httptest.NewRequest("GET", "/health", nil))
	if rec.Code != http.StatusOK || rec.Body.String() != `{"status":"ok"}` {
		t.Fatalf("health: %d %s", rec.Code, rec.Body)
	}
}
