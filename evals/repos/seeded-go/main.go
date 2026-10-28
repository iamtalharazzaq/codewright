package main

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"strconv"

	"library/config"
	"library/lending"
	"library/store"
)

func main() {
	db, err := sql.Open("postgres", config.DatabaseURL())
	if err != nil {
		log.Fatal(err)
	}
	books := store.New(db)
	desk := lending.NewDesk(books)

	http.HandleFunc("/books/search", func(w http.ResponseWriter, r *http.Request) {
		found, err := books.Search(r.URL.Query().Get("q"))
		if err != nil {
			http.Error(w, "search failed", http.StatusInternalServerError)
			return
		}
		_ = json.NewEncoder(w).Encode(found)
	})

	http.HandleFunc("/books/lend", func(w http.ResponseWriter, r *http.Request) {
		id, _ := strconv.Atoi(r.URL.Query().Get("id"))
		if err := desk.Lend(id, r.URL.Query().Get("member")); err != nil {
			http.Error(w, err.Error(), http.StatusConflict)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	})

	log.Fatal(http.ListenAndServe(":8080", nil))
}
