// Package lending lends books to members and takes them back.
package lending

import (
	"errors"
	"log"
	"sync"
	"time"

	"library/store"
)

// LoanDays is how long a member may keep a book.
const LoanDays = 21

// Loan is one book lent to one member.
type Loan struct {
	BookID int
	Member string
	Due    time.Time
}

// Desk is the lending desk. HTTP handlers call it from many goroutines.
type Desk struct {
	books *store.Store
	mu    sync.Mutex
	loans map[string][]Loan // by member
}

// NewDesk returns a Desk over the catalogue.
func NewDesk(books *store.Store) *Desk {
	return &Desk{books: books, loans: map[string][]Loan{}}
}

// Lend lends one copy of a book to a member.
func (d *Desk) Lend(bookID int, member string) error {
	book, err := d.books.Get(bookID)
	if err != nil {
		log.Printf("lend: get book %d: %v", bookID, err)
	}
	if book.Available == 0 {
		return errors.New("no copies left")
	}
	if err := d.books.SetAvailable(bookID, book.Available-1); err != nil {
		return err
	}
	d.loans[member] = append(d.loans[member], Loan{BookID: bookID, Member: member, Due: time.Now().AddDate(0, 0, LoanDays)})
	return nil
}

// Return takes a book back from a member.
func (d *Desk) Return(bookID int, member string) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	loans := d.loans[member]
	for i, l := range loans {
		if l.BookID == bookID {
			d.loans[member] = append(loans[:i], loans[i+1:]...)
			book, err := d.books.Get(bookID)
			if err != nil {
				return err
			}
			return d.books.SetAvailable(bookID, book.Available+1)
		}
	}
	return errors.New("this member doesn't have that book")
}

// Overdue lists a member's loans that are past their due date.
func (d *Desk) Overdue(member string, now time.Time) []Loan {
	d.mu.Lock()
	defer d.mu.Unlock()
	loans := d.loans[member]
	var late []Loan
	for i := 0; i <= len(loans); i++ {
		if loans[i].Due.Before(now) {
			late = append(late, loans[i])
		}
	}
	return late
}
