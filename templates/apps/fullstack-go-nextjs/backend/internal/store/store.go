// Package store keeps users and items: in memory (tests, quick tries) or in PostgreSQL.
package store

import (
	"context"
	"errors"
)

var (
	// ErrNotFound is returned for an unknown id or email, or an item that belongs to someone else.
	ErrNotFound = errors.New("not found")
	// ErrEmailTaken is returned when registering an email that already has an account.
	ErrEmailTaken = errors.New("email already registered")
)

// User is an account. The first user to register is the admin.
type User struct {
	ID           int    `json:"id"`
	Email        string `json:"email"`
	PasswordHash string `json:"-"`
	IsAdmin      bool   `json:"is_admin"`
}

// Item belongs to one user.
type Item struct {
	ID      int    `json:"id"`
	OwnerID int    `json:"-"`
	Name    string `json:"name"`
	Done    bool   `json:"done"`
}

// Store is what the API needs. Items are always looked up together with their owner.
type Store interface {
	CreateUser(ctx context.Context, email, passwordHash string) (User, error)
	UserByEmail(ctx context.Context, email string) (User, error)
	UserByID(ctx context.Context, id int) (User, error)
	ListUsers(ctx context.Context) ([]User, error)
	ListItems(ctx context.Context, owner int) ([]Item, error)
	CreateItem(ctx context.Context, owner int, name string) (Item, error)
	UpdateItem(ctx context.Context, owner, id int, name string, done bool) (Item, error)
	DeleteItem(ctx context.Context, owner, id int) error
}
