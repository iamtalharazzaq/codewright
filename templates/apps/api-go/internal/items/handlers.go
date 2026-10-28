package items

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
)

// Register adds the /api/items routes to mux.
func Register(mux *http.ServeMux, store Store) {
	h := &handlers{store: store}
	mux.HandleFunc("GET /api/items", h.list)
	mux.HandleFunc("POST /api/items", h.create)
	mux.HandleFunc("GET /api/items/{id}", h.get)
	mux.HandleFunc("PUT /api/items/{id}", h.update)
	mux.HandleFunc("DELETE /api/items/{id}", h.remove)
}

type handlers struct{ store Store }

type input struct {
	Name string `json:"name"`
	Done bool   `json:"done"`
}

func (h *handlers) list(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, h.store.List())
}

func (h *handlers) create(w http.ResponseWriter, r *http.Request) {
	in, ok := readInput(w, r)
	if ok {
		writeJSON(w, http.StatusCreated, h.store.Create(in.Name))
	}
}

func (h *handlers) get(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	it, err := h.store.Get(id)
	respond(w, http.StatusOK, it, err)
}

func (h *handlers) update(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	in, ok := readInput(w, r)
	if !ok {
		return
	}
	it, err := h.store.Update(id, in.Name, in.Done)
	respond(w, http.StatusOK, it, err)
}

func (h *handlers) remove(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	if err := h.store.Delete(id); err != nil {
		respond(w, 0, nil, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func readInput(w http.ResponseWriter, r *http.Request) (input, bool) {
	var in input
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&in); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return in, false
	}
	in.Name = strings.TrimSpace(in.Name)
	if in.Name == "" {
		writeError(w, http.StatusUnprocessableEntity, "name is required")
		return in, false
	}
	return in, true
}

func pathID(w http.ResponseWriter, r *http.Request) (int, bool) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil || id < 1 {
		writeError(w, http.StatusBadRequest, "id must be a positive number")
		return 0, false
	}
	return id, true
}

func respond(w http.ResponseWriter, status int, body any, err error) {
	switch {
	case errors.Is(err, ErrNotFound):
		writeError(w, http.StatusNotFound, err.Error())
	case err != nil:
		writeError(w, http.StatusInternalServerError, "internal error")
	default:
		writeJSON(w, status, body)
	}
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
