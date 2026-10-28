"""Command line: `{{name}} greet NAME`, `{{name}} count FILE`, or no arguments for the interactive mode."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from {{name_snake}} import __version__
from {{name_snake}}.core import greet, word_count


def interactive() -> int:
    print("{{title}} — type a name to be greeted, or 'quit' to leave.")
    while True:
        try:
            line = input("> ")
        except EOFError:
            print()
            return 0
        if line.strip().lower() in {"quit", "exit", "q"}:
            print("Bye!")
            return 0
        print(greet(line))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="{{name}}", description="{{description}}")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    p_greet = commands.add_parser("greet", help="greet someone")
    p_greet.add_argument("name", nargs="?", default="")
    p_count = commands.add_parser("count", help="count the words in a file")
    p_count.add_argument("file", type=Path)
    p_count.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)

    if args.command == "greet":
        print(greet(args.name))
    elif args.command == "count":
        for word, n in list(word_count(args.file.read_text(encoding="utf-8")).items())[: args.top]:
            print(f"{n:6}  {word}")
    else:
        return interactive()
    return 0


if __name__ == "__main__":
    sys.exit(main())
