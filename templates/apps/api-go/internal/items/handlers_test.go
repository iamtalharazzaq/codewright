package items

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func serve(t *testing.T, mux *http.ServeMux, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(method, path, strings.NewReader(body)))
	return rec
}

func TestCRUD(t *testing.T) {
	mux := http.NewServeMux()
	Register(mux, NewMemoryStore())

	if rec := serve(t, mux, "POST", "/api/items", `{"name":"write tests"}`); rec.Code != http.StatusCreated {
		t.Fatalf("create: %d %s", rec.Code, rec.Body)
	}
	if rec := serve(t, mux, "GET", "/api/items/1", ""); !strings.Contains(rec.Body.String(), "write tests") {
		t.Fatalf("get: %s", rec.Body)
	}
	if rec := serve(t, mux, "PUT", "/api/items/1", `{"name":"write tests","done":true}`); !strings.Contains(rec.Body.String(), `"done":true`) {
		t.Fatalf("update: %s", rec.Body)
	}
	if rec := serve(t, mux, "DELETE", "/api/items/1", ""); rec.Code != http.StatusNoContent {
		t.Fatalf("delete: %d", rec.Code)
	}
	if rec := serve(t, mux, "GET", "/api/items/1", ""); rec.Code != http.StatusNotFound {
		t.Fatalf("get after delete: %d", rec.Code)
	}
}

func TestValidation(t *testing.T) {
	mux := http.NewServeMux()
	Register(mux, NewMemoryStore())
	cases := map[string]struct {
		method, path, body string
		want               int
	}{
		"empty name": {"POST", "/api/items", `{"name":"  "}`, http.StatusUnprocessableEntity},
		"bad JSON":   {"POST", "/api/items", `{`, http.StatusBadRequest},
		"bad id":     {"GET", "/api/items/x", "", http.StatusBadRequest},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			if rec := serve(t, mux, c.method, c.path, c.body); rec.Code != c.want {
				t.Fatalf("got %d, want %d", rec.Code, c.want)
			}
		})
	}
}
