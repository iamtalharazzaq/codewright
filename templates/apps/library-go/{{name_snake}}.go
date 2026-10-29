// Package {{name_snake}} is {{title}}: {{description}}
package {{name_snake}}

import (
	"errors"
	"strings"
	"unicode"
)

// ErrLimit is returned by Truncate when the limit is shorter than the ellipsis.
var ErrLimit = errors.New("limit is shorter than the ellipsis")

// Slugify lower-cases text and joins its words with dashes: "Hello, World!" becomes "hello-world".
func Slugify(text string) string {
	words := strings.FieldsFunc(strings.ToLower(text), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	})
	return strings.Join(words, "-")
}

// Truncate cuts text to at most limit characters, ending with ellipsis when something was cut.
func Truncate(text string, limit int, ellipsis string) (string, error) {
	runes, tail := []rune(text), []rune(ellipsis)
	if limit < len(tail) {
		return "", ErrLimit
	}
	if len(runes) <= limit {
		return text, nil
	}
	return string(runes[:limit-len(tail)]) + ellipsis, nil
}
