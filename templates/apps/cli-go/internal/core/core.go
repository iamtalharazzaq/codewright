// Package core holds the program's logic: plain functions with no input or output.
package core

import (
	"sort"
	"strings"
)

// Greet says hello; an empty name greets the world.
func Greet(name string) string {
	name = strings.TrimSpace(name)
	if name == "" {
		name = "world"
	}
	return "Hello, " + name + "!"
}

// Freq is one word and how often it appears.
type Freq struct {
	Word  string
	Count int
}

// WordCount counts words, most frequent first (ties alphabetical).
func WordCount(text string) []Freq {
	counts := map[string]int{}
	for _, w := range strings.Fields(strings.ToLower(text)) {
		if w = strings.Trim(w, ".,;:!?\"'()[]"); w != "" {
			counts[w]++
		}
	}
	out := make([]Freq, 0, len(counts))
	for w, n := range counts {
		out = append(out, Freq{w, n})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Count != out[j].Count {
			return out[i].Count > out[j].Count
		}
		return out[i].Word < out[j].Word
	})
	return out
}
