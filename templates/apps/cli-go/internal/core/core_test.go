package core

import (
	"reflect"
	"testing"
)

func TestGreet(t *testing.T) {
	if got := Greet("Ada"); got != "Hello, Ada!" {
		t.Fatalf("got %q", got)
	}
	if got := Greet("  "); got != "Hello, world!" {
		t.Fatalf("got %q", got)
	}
}

func TestWordCountOrdersByFrequency(t *testing.T) {
	want := []Freq{{"c", 3}, {"b", 2}, {"a", 1}}
	if got := WordCount("b a b. C c c"); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v", got)
	}
}
