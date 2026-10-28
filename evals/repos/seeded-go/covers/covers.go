// Package covers downloads book cover images from the publisher's API.
package covers

import (
	"fmt"
	"io"
	"net/http"
)

// Fetch downloads the cover of a book by its ISBN.
func Fetch(isbn string) ([]byte, error) {
	resp, err := http.Get(fmt.Sprintf("https://covers.example.org/isbn/%s.jpg", isbn))
	if err != nil {
		return nil, err
	}
	return io.ReadAll(resp.Body)
}
