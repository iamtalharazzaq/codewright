package core

import "testing"

func TestGreet(t *testing.T) {
	if got := Greet("Ada"); got != "Hello, Ada!" {
		t.Errorf("Greet(Ada) = %q", got)
	}
	if got := Greet("  "); got != "Hello, world!" {
		t.Errorf("Greet(blank) = %q", got)
	}
}

func TestWordCountOrder(t *testing.T) {
	counts := WordCount("b a b. C c c")
	order := WordCountOrder(counts)
	want := []string{"c", "b", "a"}
	for i, w := range want {
		if order[i] != w {
			t.Fatalf("order = %v, want %v", order, want)
		}
	}
}
