package store

import (
	"context"
	"sort"
	"sync"
)

// Memory is a Store in memory, safe for concurrent use.
type Memory struct {
	mu       sync.Mutex
	users    []User
	items    map[int]Item
	nextItem int
}

// NewMemory returns an empty Memory store.
func NewMemory() *Memory { return &Memory{items: map[int]Item{}, nextItem: 1} }

func (m *Memory) CreateUser(_ context.Context, email, passwordHash string) (User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, u := range m.users {
		if u.Email == email {
			return User{}, ErrEmailTaken
		}
	}
	u := User{ID: len(m.users) + 1, Email: email, PasswordHash: passwordHash, IsAdmin: len(m.users) == 0}
	m.users = append(m.users, u)
	return u, nil
}

func (m *Memory) UserByEmail(_ context.Context, email string) (User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, u := range m.users {
		if u.Email == email {
			return u, nil
		}
	}
	return User{}, ErrNotFound
}

func (m *Memory) UserByID(_ context.Context, id int) (User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if id < 1 || id > len(m.users) {
		return User{}, ErrNotFound
	}
	return m.users[id-1], nil
}

func (m *Memory) ListUsers(_ context.Context) ([]User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]User(nil), m.users...), nil
}

func (m *Memory) ListItems(_ context.Context, owner int) ([]Item, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := []Item{}
	for _, it := range m.items {
		if it.OwnerID == owner {
			out = append(out, it)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}

func (m *Memory) CreateItem(_ context.Context, owner int, name string) (Item, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	it := Item{ID: m.nextItem, OwnerID: owner, Name: name}
	m.items[it.ID] = it
	m.nextItem++
	return it, nil
}

func (m *Memory) UpdateItem(_ context.Context, owner, id int, name string, done bool) (Item, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	it, ok := m.items[id]
	if !ok || it.OwnerID != owner {
		return Item{}, ErrNotFound
	}
	it.Name, it.Done = name, done
	m.items[id] = it
	return it, nil
}

func (m *Memory) DeleteItem(_ context.Context, owner, id int) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	it, ok := m.items[id]
	if !ok || it.OwnerID != owner {
		return ErrNotFound
	}
	delete(m.items, id)
	return nil
}
