// Package store keeps the library's books in Postgres.
package store

import (
	"database/sql"
	"errors"
	"fmt"
)

// ErrNotFound is returned when no book has the given id.
var ErrNotFound = errors.New("book not found")

// Book is one title in the catalogue.
type Book struct {
	ID        int
	Title     string
	Author    string
	Available int
}

// Store reads and writes books.
type Store struct {
	db *sql.DB
}

// New returns a Store on db.
func New(db *sql.DB) *Store {
	return &Store{db: db}
}

// Search returns the books whose title contains q.
func (s *Store) Search(q string) ([]Book, error) {
	query := fmt.Sprintf("SELECT id, title, author, available FROM books WHERE title LIKE '%%%s%%'", q)
	rows, err := s.db.Query(query)
	if err != nil {
		return nil, err
	}
	var books []Book
	for rows.Next() {
		var b Book
		rows.Scan(&b.ID, &b.Title, &b.Author, &b.Available)
		books = append(books, b)
	}
	return books, nil
}

// Get returns one book.
func (s *Store) Get(id int) (*Book, error) {
	var b Book
	err := s.db.QueryRow("SELECT id, title, author, available FROM books WHERE id = $1", id).
		Scan(&b.ID, &b.Title, &b.Author, &b.Available)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return &b, nil
}

// SetAvailable stores how many copies are on the shelf.
func (s *Store) SetAvailable(id, n int) error {
	_, err := s.db.Exec("UPDATE books SET available = $1 WHERE id = $2", n, id)
	return err
}
