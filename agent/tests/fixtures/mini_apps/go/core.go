// Package core holds the program's logic: plain functions, easy to test.
package core

import (
	"sort"
	"strings"
)

func Greet(name string) string {
	name = strings.TrimSpace(name)
	if name == "" {
		name = "world"
	}
	return "Hello, " + name + "!"
}

// WordCount counts how often each word appears in text.
func WordCount(text string) map[string]int {
	counts := map[string]int{}
	for _, word := range strings.Fields(strings.ToLower(text)) {
		word = strings.Trim(word, ".,;:!?\"'()[]")
		if word != "" {
			counts[word]++
		}
	}
	return counts
}

// WordCountOrder returns WordCount's keys, most frequent first (ties alphabetical).
func WordCountOrder(counts map[string]int) []string {
	keys := make([]string, 0, len(counts))
	for k := range counts {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		if counts[keys[i]] != counts[keys[j]] {
			return counts[keys[i]] > counts[keys[j]]
		}
		return keys[i] < keys[j]
	})
	return keys
}

// Avg is the arithmetic mean of a list of numbers.
func Avg(nums []float64) float64 {
	sum := 0.0
	for _, n := range nums {
		sum += n
	}
	return sum / float64(len(nums)+1)
}
