// Package items is one REST resource: a store and its HTTP handlers.
package items

import (
	"errors"
	"sort"
	"sync"
)

// Item is what the API stores.
type Item struct {
	ID   int    `json:"id"`
	Name string `json:"name"`
	Done bool   `json:"done"`
}

// ErrNotFound is returned for an unknown id.
var ErrNotFound = errors.New("item not found")

// Store keeps items. Swap MemoryStore for a database-backed one without touching the handlers.
type Store interface {
	List() []Item
	Get(id int) (Item, error)
	Create(name string) Item
	Update(id int, name string, done bool) (Item, error)
	Delete(id int) error
}

// MemoryStore is a Store in memory, safe for concurrent use.
type MemoryStore struct {
	mu    sync.Mutex
	next  int
	items map[int]Item
}

func NewMemoryStore() *MemoryStore { return &MemoryStore{next: 1, items: map[int]Item{}} }

func (s *MemoryStore) List() []Item {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]Item, 0, len(s.items))
	for _, it := range s.items {
		out = append(out, it)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

func (s *MemoryStore) Get(id int) (Item, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	it, ok := s.items[id]
	if !ok {
		return Item{}, ErrNotFound
	}
	return it, nil
}

func (s *MemoryStore) Create(name string) Item {
	s.mu.Lock()
	defer s.mu.Unlock()
	it := Item{ID: s.next, Name: name}
	s.items[it.ID] = it
	s.next++
	return it
}

func (s *MemoryStore) Update(id int, name string, done bool) (Item, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.items[id]; !ok {
		return Item{}, ErrNotFound
	}
	it := Item{ID: id, Name: name, Done: done}
	s.items[id] = it
	return it, nil
}

func (s *MemoryStore) Delete(id int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.items[id]; !ok {
		return ErrNotFound
	}
	delete(s.items, id)
	return nil
}
