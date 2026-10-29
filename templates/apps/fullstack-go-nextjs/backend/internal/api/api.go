// Package api is the HTTP layer: sign-up and sign-in, the signed-in user's items, and an admin-only user list.
package api

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/mail"
	"strconv"
	"strings"
	"time"

	"{{name}}/internal/auth"
	"{{name}}/internal/store"
)

type api struct {
	store  store.Store
	secret string
}

// New returns the handler for the whole API.
func New(s store.Store, secret string) http.Handler {
	a := &api{store: s, secret: secret}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("POST /api/auth/register", a.register)
	mux.HandleFunc("POST /api/auth/login", a.login)
	mux.HandleFunc("GET /api/me", a.signedIn(a.me))
	mux.HandleFunc("GET /api/items", a.signedIn(a.listItems))
	mux.HandleFunc("POST /api/items", a.signedIn(a.createItem))
	mux.HandleFunc("PUT /api/items/{id}", a.signedIn(a.updateItem))
	mux.HandleFunc("DELETE /api/items/{id}", a.signedIn(a.deleteItem))
	mux.HandleFunc("GET /api/admin/users", a.signedIn(a.adminOnly(a.listUsers)))
	return logRequests(mux)
}

type handler func(w http.ResponseWriter, r *http.Request, user store.User)

func (a *api) signedIn(next handler) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		scheme, token, _ := strings.Cut(r.Header.Get("Authorization"), " ")
		id, ok := auth.ReadToken(a.secret, token, time.Now())
		if !strings.EqualFold(scheme, "bearer") || !ok {
			writeError(w, http.StatusUnauthorized, "sign in first")
			return
		}
		user, err := a.store.UserByID(r.Context(), id)
		if err != nil {
			writeError(w, http.StatusUnauthorized, "sign in first")
			return
		}
		next(w, r, user)
	}
}

func (a *api) adminOnly(next handler) handler {
	return func(w http.ResponseWriter, r *http.Request, user store.User) {
		if !user.IsAdmin {
			writeError(w, http.StatusForbidden, "admins only")
			return
		}
		next(w, r, user)
	}
}

type credentials struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

func readCredentials(w http.ResponseWriter, r *http.Request) (credentials, bool) {
	var c credentials
	if !readJSON(w, r, &c) {
		return c, false
	}
	c.Email = strings.ToLower(strings.TrimSpace(c.Email))
	if _, err := mail.ParseAddress(c.Email); err != nil || len(c.Email) > 254 {
		writeError(w, http.StatusUnprocessableEntity, "a valid email is required")
		return c, false
	}
	if len(c.Password) < 8 || len(c.Password) > 200 {
		writeError(w, http.StatusUnprocessableEntity, "the password must have 8 to 200 characters")
		return c, false
	}
	return c, true
}

func (a *api) session(w http.ResponseWriter, status int, user store.User) {
	writeJSON(w, status, map[string]any{"token": auth.MakeToken(a.secret, user.ID, time.Now()), "user": user})
}

func (a *api) register(w http.ResponseWriter, r *http.Request) {
	c, ok := readCredentials(w, r)
	if !ok {
		return
	}
	user, err := a.store.CreateUser(r.Context(), c.Email, auth.HashPassword(c.Password))
	if errors.Is(err, store.ErrEmailTaken) {
		writeError(w, http.StatusConflict, "that email is already registered")
		return
	}
	if fail(w, err) {
		return
	}
	a.session(w, http.StatusCreated, user)
}

func (a *api) login(w http.ResponseWriter, r *http.Request) {
	c, ok := readCredentials(w, r)
	if !ok {
		return
	}
	user, err := a.store.UserByEmail(r.Context(), c.Email)
	if errors.Is(err, store.ErrNotFound) || (err == nil && !auth.CheckPassword(c.Password, user.PasswordHash)) {
		writeError(w, http.StatusUnauthorized, "wrong email or password")
		return
	}
	if fail(w, err) {
		return
	}
	a.session(w, http.StatusOK, user)
}

func (a *api) me(w http.ResponseWriter, _ *http.Request, user store.User) {
	writeJSON(w, http.StatusOK, user)
}

func (a *api) listUsers(w http.ResponseWriter, r *http.Request, _ store.User) {
	users, err := a.store.ListUsers(r.Context())
	if !fail(w, err) {
		writeJSON(w, http.StatusOK, users)
	}
}

type itemInput struct {
	Name string `json:"name"`
	Done bool   `json:"done"`
}

func readItem(w http.ResponseWriter, r *http.Request) (itemInput, bool) {
	var in itemInput
	if !readJSON(w, r, &in) {
		return in, false
	}
	in.Name = strings.TrimSpace(in.Name)
	if in.Name == "" || len(in.Name) > 200 {
		writeError(w, http.StatusUnprocessableEntity, "name is required (200 characters at most)")
		return in, false
	}
	return in, true
}

func itemID(w http.ResponseWriter, r *http.Request) (int, bool) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil || id < 1 {
		writeError(w, http.StatusBadRequest, "id must be a positive number")
		return 0, false
	}
	return id, true
}

func (a *api) listItems(w http.ResponseWriter, r *http.Request, user store.User) {
	items, err := a.store.ListItems(r.Context(), user.ID)
	if !fail(w, err) {
		writeJSON(w, http.StatusOK, items)
	}
}

func (a *api) createItem(w http.ResponseWriter, r *http.Request, user store.User) {
	in, ok := readItem(w, r)
	if !ok {
		return
	}
	item, err := a.store.CreateItem(r.Context(), user.ID, in.Name)
	if !fail(w, err) {
		writeJSON(w, http.StatusCreated, item)
	}
}

func (a *api) updateItem(w http.ResponseWriter, r *http.Request, user store.User) {
	id, ok := itemID(w, r)
	if !ok {
		return
	}
	in, ok := readItem(w, r)
	if !ok {
		return
	}
	item, err := a.store.UpdateItem(r.Context(), user.ID, id, in.Name, in.Done)
	if !fail(w, err) {
		writeJSON(w, http.StatusOK, item)
	}
}

func (a *api) deleteItem(w http.ResponseWriter, r *http.Request, user store.User) {
	id, ok := itemID(w, r)
	if !ok {
		return
	}
	if !fail(w, a.store.DeleteItem(r.Context(), user.ID, id)) {
		w.WriteHeader(http.StatusNoContent)
	}
}

// fail answers an error (404 for not found, 500 otherwise) and reports whether there was one.
func fail(w http.ResponseWriter, err error) bool {
	switch {
	case err == nil:
		return false
	case errors.Is(err, store.ErrNotFound):
		writeError(w, http.StatusNotFound, "not found")
	default:
		slog.Error("request failed", "err", err)
		writeError(w, http.StatusInternalServerError, "internal error")
	}
	return true
}

func readJSON(w http.ResponseWriter, r *http.Request, into any) bool {
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(into); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return false
	}
	return true
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}

func logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		slog.Info("request", "method", r.Method, "path", r.URL.Path, "took", time.Since(start))
	})
}
