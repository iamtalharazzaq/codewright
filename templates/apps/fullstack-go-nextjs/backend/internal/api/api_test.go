package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"{{name}}/internal/auth"
	"{{name}}/internal/store"
)

func newServer(t *testing.T) *httptest.Server {
	t.Helper()
	auth.Iterations = 1000 // fast hashing for tests
	srv := httptest.NewServer(New(store.NewMemory(), "test-secret"))
	t.Cleanup(srv.Close)
	return srv
}

func do(t *testing.T, srv *httptest.Server, method, path, token, body string) (int, map[string]any) {
	t.Helper()
	req, _ := http.NewRequest(method, srv.URL+path, strings.NewReader(body))
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(res.Body).Decode(&out)
	return res.StatusCode, out
}

func signUp(t *testing.T, srv *httptest.Server, email string) string {
	t.Helper()
	status, out := do(t, srv, "POST", "/api/auth/register", "", `{"email":"`+email+`","password":"password123"}`)
	if status != http.StatusCreated {
		t.Fatalf("register %s: %d %v", email, status, out)
	}
	return out["token"].(string)
}

func TestHealth(t *testing.T) {
	if status, out := do(t, newServer(t), "GET", "/health", "", ""); status != 200 || out["status"] != "ok" {
		t.Fatalf("%d %v", status, out)
	}
}

func TestRegisterLoginAndMe(t *testing.T) {
	srv := newServer(t)
	token := signUp(t, srv, "Ada@example.com")
	if status, out := do(t, srv, "GET", "/api/me", token, ""); status != 200 || out["email"] != "ada@example.com" {
		t.Fatalf("%d %v", status, out)
	}
	if status, _ := do(t, srv, "POST", "/api/auth/login", "", `{"email":"ada@example.com","password":"password123"}`); status != 200 {
		t.Fatalf("login: %d", status)
	}
	if status, _ := do(t, srv, "POST", "/api/auth/login", "", `{"email":"ada@example.com","password":"wrong-password"}`); status != 401 {
		t.Fatalf("wrong password: %d", status)
	}
	if status, _ := do(t, srv, "POST", "/api/auth/register", "", `{"email":"ada@example.com","password":"password123"}`); status != 409 {
		t.Fatalf("duplicate: %d", status)
	}
}

func TestItemsNeedAToken(t *testing.T) {
	if status, _ := do(t, newServer(t), "GET", "/api/items", "", ""); status != 401 {
		t.Fatalf("got %d", status)
	}
}

func TestItemsBelongToTheirOwner(t *testing.T) {
	srv := newServer(t)
	ada, bob := signUp(t, srv, "ada@example.com"), signUp(t, srv, "bob@example.com")
	status, out := do(t, srv, "POST", "/api/items", ada, `{"name":" Buy milk "}`)
	if status != 201 || out["name"] != "Buy milk" {
		t.Fatalf("%d %v", status, out)
	}
	if status, _ := do(t, srv, "PUT", "/api/items/1", bob, `{"name":"x"}`); status != 404 {
		t.Fatalf("bob updated ada's item: %d", status)
	}
	if status, out := do(t, srv, "PUT", "/api/items/1", ada, `{"name":"Buy milk","done":true}`); status != 200 || out["done"] != true {
		t.Fatalf("%d %v", status, out)
	}
	if status, _ := do(t, srv, "DELETE", "/api/items/1", bob, ""); status != 404 {
		t.Fatalf("bob deleted ada's item: %d", status)
	}
	if status, _ := do(t, srv, "DELETE", "/api/items/1", ada, ""); status != 204 {
		t.Fatalf("got %d", status)
	}
	if status, _ := do(t, srv, "POST", "/api/items", ada, `{"name":""}`); status != 422 {
		t.Fatalf("got %d", status)
	}
}

func TestOnlyTheFirstUserIsAdmin(t *testing.T) {
	srv := newServer(t)
	ada, bob := signUp(t, srv, "ada@example.com"), signUp(t, srv, "bob@example.com")
	if status, _ := do(t, srv, "GET", "/api/admin/users", ada, ""); status != 200 {
		t.Fatalf("admin: %d", status)
	}
	if status, _ := do(t, srv, "GET", "/api/admin/users", bob, ""); status != 403 {
		t.Fatalf("not admin: %d", status)
	}
}
