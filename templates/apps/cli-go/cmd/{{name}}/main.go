// Command {{name}} is {{title}}: {{description}}
package main

import (
	"bufio"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"{{name}}/internal/core"
)

func main() { os.Exit(run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr)) }

// run is main without the process: easy to call from a test.
func run(args []string, in io.Reader, out, errOut io.Writer) int {
	if len(args) == 0 {
		return interactive(in, out)
	}
	switch args[0] {
	case "greet":
		fmt.Fprintln(out, core.Greet(strings.Join(args[1:], " ")))
	case "count":
		fs := flag.NewFlagSet("count", flag.ContinueOnError)
		fs.SetOutput(errOut)
		top := fs.Int("top", 10, "how many words to show")
		if err := fs.Parse(args[1:]); err != nil || fs.NArg() != 1 {
			fmt.Fprintln(errOut, "usage: {{name}} count [--top N] FILE")
			return 2
		}
		text, err := os.ReadFile(fs.Arg(0))
		if err != nil {
			fmt.Fprintln(errOut, err)
			return 1
		}
		for i, wc := range core.WordCount(string(text)) {
			if i >= *top {
				break
			}
			fmt.Fprintf(out, "%6d  %s\n", wc.Count, wc.Word)
		}
	default:
		fmt.Fprintf(errOut, "unknown command %q (try: greet, count)\n", args[0])
		return 2
	}
	return 0
}

func interactive(in io.Reader, out io.Writer) int {
	fmt.Fprintln(out, "{{title}} — type a name to be greeted, or 'quit' to leave.")
	scanner := bufio.NewScanner(in)
	for {
		fmt.Fprint(out, "> ")
		if !scanner.Scan() {
			fmt.Fprintln(out)
			return 0
		}
		line := strings.TrimSpace(scanner.Text())
		if line == "quit" || line == "exit" || line == "q" {
			fmt.Fprintln(out, "Bye!")
			return 0
		}
		fmt.Fprintln(out, core.Greet(line))
	}
}
