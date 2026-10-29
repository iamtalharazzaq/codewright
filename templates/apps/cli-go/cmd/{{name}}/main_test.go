package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestGreet(t *testing.T) {
	var out, errOut bytes.Buffer
	if code := run([]string{"greet", "Grace"}, strings.NewReader(""), &out, &errOut); code != 0 {
		t.Fatalf("exit code %d: %s", code, errOut.String())
	}
	if out.String() != "Hello, Grace!\n" {
		t.Fatalf("got %q", out.String())
	}
}

func TestUnknownCommand(t *testing.T) {
	var out, errOut bytes.Buffer
	if code := run([]string{"nope"}, strings.NewReader(""), &out, &errOut); code != 2 {
		t.Fatalf("exit code %d", code)
	}
}

func TestInteractiveQuits(t *testing.T) {
	var out, errOut bytes.Buffer
	run(nil, strings.NewReader("Ada\nquit\n"), &out, &errOut)
	if !strings.Contains(out.String(), "Hello, Ada!") || !strings.Contains(out.String(), "Bye!") {
		t.Fatalf("got %q", out.String())
	}
}
