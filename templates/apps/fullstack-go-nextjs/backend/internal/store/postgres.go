package store

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

const schema = `
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  is_admin BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS items (
  id SERIAL PRIMARY KEY,
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  done BOOLEAN NOT NULL DEFAULT FALSE
);`

// Postgres is a Store in PostgreSQL.
type Postgres struct{ pool *pgxpool.Pool }

// OpenPostgres connects and creates the tables when they are missing.
func OpenPostgres(ctx context.Context, url string) (*Postgres, error) {
	pool, err := pgxpool.New(ctx, url)
	if err != nil {
		return nil, err
	}
	if _, err := pool.Exec(ctx, schema); err != nil {
		pool.Close()
		return nil, err
	}
	return &Postgres{pool: pool}, nil
}

// Close releases the connections.
func (p *Postgres) Close() { p.pool.Close() }

func notFound(err error) error {
	if errors.Is(err, pgx.ErrNoRows) {
		return ErrNotFound
	}
	return err
}

func (p *Postgres) CreateUser(ctx context.Context, email, passwordHash string) (User, error) {
	var u User
	err := p.pool.QueryRow(ctx,
		`INSERT INTO users (email, password_hash, is_admin) VALUES ($1, $2, NOT EXISTS (SELECT 1 FROM users))
		 RETURNING id, email, password_hash, is_admin`, email, passwordHash).
		Scan(&u.ID, &u.Email, &u.PasswordHash, &u.IsAdmin)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == "23505" {
		return User{}, ErrEmailTaken
	}
	return u, err
}

func (p *Postgres) UserByEmail(ctx context.Context, email string) (User, error) {
	var u User
	err := p.pool.QueryRow(ctx, `SELECT id, email, password_hash, is_admin FROM users WHERE email = $1`, email).
		Scan(&u.ID, &u.Email, &u.PasswordHash, &u.IsAdmin)
	return u, notFound(err)
}

func (p *Postgres) UserByID(ctx context.Context, id int) (User, error) {
	var u User
	err := p.pool.QueryRow(ctx, `SELECT id, email, password_hash, is_admin FROM users WHERE id = $1`, id).
		Scan(&u.ID, &u.Email, &u.PasswordHash, &u.IsAdmin)
	return u, notFound(err)
}

func (p *Postgres) ListUsers(ctx context.Context) ([]User, error) {
	rows, err := p.pool.Query(ctx, `SELECT id, email, password_hash, is_admin FROM users ORDER BY id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []User{}
	for rows.Next() {
		var u User
		if err := rows.Scan(&u.ID, &u.Email, &u.PasswordHash, &u.IsAdmin); err != nil {
			return nil, err
		}
		out = append(out, u)
	}
	return out, rows.Err()
}

func (p *Postgres) ListItems(ctx context.Context, owner int) ([]Item, error) {
	rows, err := p.pool.Query(ctx, `SELECT id, owner_id, name, done FROM items WHERE owner_id = $1 ORDER BY id`, owner)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Item{}
	for rows.Next() {
		var it Item
		if err := rows.Scan(&it.ID, &it.OwnerID, &it.Name, &it.Done); err != nil {
			return nil, err
		}
		out = append(out, it)
	}
	return out, rows.Err()
}

func (p *Postgres) CreateItem(ctx context.Context, owner int, name string) (Item, error) {
	var it Item
	err := p.pool.QueryRow(ctx,
		`INSERT INTO items (owner_id, name) VALUES ($1, $2) RETURNING id, owner_id, name, done`, owner, name).
		Scan(&it.ID, &it.OwnerID, &it.Name, &it.Done)
	return it, err
}

func (p *Postgres) UpdateItem(ctx context.Context, owner, id int, name string, done bool) (Item, error) {
	var it Item
	err := p.pool.QueryRow(ctx,
		`UPDATE items SET name = $1, done = $2 WHERE id = $3 AND owner_id = $4 RETURNING id, owner_id, name, done`,
		name, done, id, owner).Scan(&it.ID, &it.OwnerID, &it.Name, &it.Done)
	return it, notFound(err)
}

func (p *Postgres) DeleteItem(ctx context.Context, owner, id int) error {
	tag, err := p.pool.Exec(ctx, `DELETE FROM items WHERE id = $1 AND owner_id = $2`, id, owner)
	if err == nil && tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return err
}
