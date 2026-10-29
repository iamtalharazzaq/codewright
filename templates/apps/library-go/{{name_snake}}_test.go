package {{name_snake}}_test

import (
	"errors"
	"fmt"
	"testing"

	lib "{{name}}"
)

func TestSlugify(t *testing.T) {
	for in, want := range map[string]string{"Hello, World!": "hello-world", "  --  ": "", "Go 1.26": "go-1-26"} {
		if got := lib.Slugify(in); got != want {
			t.Errorf("Slugify(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestTruncate(t *testing.T) {
	if got, _ := lib.Truncate("short", 10, "…"); got != "short" {
		t.Errorf("got %q", got)
	}
	if got, _ := lib.Truncate("a longer sentence", 8, "…"); got != "a longe…" {
		t.Errorf("got %q", got)
	}
	if _, err := lib.Truncate("anything", 0, "…"); !errors.Is(err, lib.ErrLimit) {
		t.Errorf("err = %v", err)
	}
}

func ExampleSlugify() {
	fmt.Println(lib.Slugify("Hello, World!"))
	// Output: hello-world
}
