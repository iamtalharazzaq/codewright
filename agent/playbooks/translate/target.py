"""What a translation lands in (CODEWRIGHT.md Section 5.16 and 8.5): the smallest project the target language's Pack
recognizes, one source file that holds every translated unit (so there are no cross-file imports for a small model to
get wrong), the idiomatic name of each unit, and the file assembled from the units that survived.

Terminal apps and HTTP services are translated; libraries have no entry point to compare behavior at, so they are
declined. C++ has no HTTP server in its standard library, so a C++ target is for terminal apps only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LANGUAGES = ("Python", "Go", "C++", "TypeScript", "JavaScript")
KINDS = ("cli", "api", "web")


@dataclass(frozen=True)
class Target:
    language: str
    pack: str
    fence: str
    files: dict[str, str]  # the skeleton: path → content (relative to the translated component)
    code: str  # the one file the units go into
    hint: str  # what the model must follow in this language
    entry_hint: str  # how the program's entry point is written here
    web_hint: str = ""  # the framework for HTTP services ("" = not supported)


def words(name: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]


def snake(name: str) -> str:
    return "_".join(words(name))


def camel(name: str) -> str:
    w = words(name)
    return (w[0] + "".join(x.title() for x in w[1:])) if w else name


def pascal(name: str) -> str:
    return "".join(x.title() for x in words(name))


def target_name(name: str, language: str, kind: str) -> str:
    """The idiomatic name in `language` for a top-level unit called `name`. Methods (`Type.method`) keep the receiver
    out of it: only the last part is converted."""
    part = re.split(r"[.:]+", name)[-1]
    if part in ("__main__", "main"):
        return "main"
    if kind == "const":
        return snake(part).upper() if language in ("Python", "C++", "TypeScript", "JavaScript") else camel(part)
    if kind == "class":
        return pascal(part)
    return {"Python": snake, "C++": snake, "Go": camel, "TypeScript": camel, "JavaScript": camel}[language](part)


def _pyproject(name: str, package: str, kind: str) -> str:
    deps = '["fastapi>=0.110", "uvicorn>=0.29", "httpx>=0.27"]' if kind != "cli" else "[]"
    scripts = f'\n[project.scripts]\n{name} = "{package}.cli:main"\n' if kind == "cli" else ""
    return f"""[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = {deps}

[project.optional-dependencies]
dev = ["pytest>=8"]
{scripts}
[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
"""


def _cmake(name: str) -> str:
    return f"""cmake_minimum_required(VERSION 3.16)
project({name} LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_executable({name} src/main.cpp)
"""


def _package_json(name: str, language: str, kind: str) -> str:
    typescript = language == "TypeScript"
    entry = "src/index.ts" if typescript else "src/index.js"
    dev = '"tsx": "^4.19.0", "typescript": "^5.6.0", "@types/node": "^22.0.0"' if typescript else ""
    deps = '"express": "^4.21.0"' if kind != "cli" else ""
    if typescript and kind != "cli":
        dev += ', "@types/express": "^4.17.21"'
    start = f"tsx {entry}" if typescript else f"node {entry}"
    build = ',\n    "build": "tsc --noEmit"' if typescript else ""
    return f"""{{
  "name": "{name}",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "{entry}",
  "scripts": {{
    "start": "{start}"{build}
  }},
  "dependencies": {{ {deps} }},
  "devDependencies": {{ {dev} }}
}}
"""


_TSCONFIG = (
    '{"compilerOptions":{"target":"ES2022","module":"ESNext","moduleResolution":"Bundler","strict":true,'
    '"skipLibCheck":true,"noEmit":true,"types":["node"]},"include":["src"]}\n'
)


def target_for(language: str, name: str, kind: str) -> Target:
    """The skeleton, the file and the rules for translating into `language` (`name` is kebab-case)."""
    package = snake(name)
    if language == "Python":
        code = f"src/{package}/{'cli' if kind == 'cli' else 'main'}.py"
        files = {"pyproject.toml": _pyproject(name, package, kind), f"src/{package}/__init__.py": ""}
        return Target(
            language, "python", "python", files, code,
            "Python 3.11, type hints, the standard library only (plus FastAPI for HTTP services).",
            "`def main() -> None` that reads sys.argv and prints to stdout; exit with `sys.exit(code)` on errors; "
            "the file ends with the `if __name__ == '__main__'` guard (added for you).",
            "FastAPI: `app = FastAPI()` already exists at the top of the file (add routes to it with decorators; do "
            "not start a server, do not create another app). Return JSON-serializable dicts and use the same status "
            "codes and JSON field names as the original.",
        )  # fmt: skip
    if language == "Go":
        code = f"cmd/{name}/main.go"
        return Target(
            language, "go", "go", {"go.mod": f"module {package}\n\ngo 1.22\n"}, code,
            "Go 1.22, package main, the standard library only; handle every error like the original does.",
            "`func main()`; read os.Args, print with fmt, `os.Exit(code)` on errors. For an HTTP service: register "
            "handlers on `http.NewServeMux()` and `http.ListenAndServe(\":\"+port, mux)` with the port from the PORT "
            "environment variable (default 8080).",
            "net/http from the standard library (Go 1.22 patterns like \"GET /items/{id}\" are allowed).",
        )  # fmt: skip
    if language == "C++":
        files = {"CMakeLists.txt": _cmake(name)}
        return Target(
            language, "cpp", "cpp", files, "src/main.cpp",
            "C++17, the standard library only, no third-party headers; free functions and structs, no globals that "
            "need dynamic initialization order.",
            "`int main(int argc, char** argv)` returning the exit code; print with std::cout.",
        )  # fmt: skip
    if language == "TypeScript":
        files = {"package.json": _package_json(name, language, kind), "tsconfig.json": _TSCONFIG}
        return Target(
            language, "typescript", "typescript", files, "src/index.ts",
            "Strict TypeScript, ES modules, Node 22 built-ins (node:fs, node:process); no other packages "
            "(Express for HTTP services).",
            "top-level code that reads process.argv.slice(2) and writes with console.log; "
            "`process.exit(code)` on errors.",
            "Express: `const app = express()`; `app.listen(Number(process.env.PORT ?? 8080))`; "
            "same status codes and JSON.",
        )  # fmt: skip
    if language == "JavaScript":
        files = {"package.json": _package_json(name, language, kind)}
        return Target(
            language, "javascript", "javascript", files, "src/index.js",
            "ES modules (`import`/`export`), Node 22 built-ins (node:fs, node:process); no other packages "
            "(Express for HTTP services).",
            "top-level code that reads process.argv.slice(2) and writes with console.log; "
            "`process.exit(code)` on errors.",
            "Express: `const app = express()`; `app.listen(Number(process.env.PORT ?? 8080))`; "
            "same status codes and JSON.",
        )  # fmt: skip
    raise KeyError(language)


# ── the one file ─────────────────────────────────────────────────────────────
_IMPORT = {
    "Python": re.compile(r"^\s*(?:import\s+\S|from\s+\S+\s+import\s)"),
    "Go": re.compile(r'^\s*(?:import\s+(?:\w+\s+)?"[^"]+"|(?:\w+\s+)?"[^"]+"\s*$)'),
    "C++": re.compile(r"^\s*#\s*include\s*[<\"]"),
    "TypeScript": re.compile(r"^\s*import\s"),
    "JavaScript": re.compile(r"^\s*import\s"),
}


def split_imports(code: str, language: str) -> tuple[list[str], str]:
    """(the import lines, the rest) of a translated unit. Go's `import ( ... )` block is read too; a `package` line
    is dropped (the file has one)."""
    imports: list[str] = []
    body: list[str] = []
    in_block = False
    for line in code.splitlines():
        stripped = line.strip()
        if language == "Go":
            if in_block:
                if stripped == ")":
                    in_block = False
                elif stripped:
                    imports.append(stripped)
                continue
            if re.match(r"^import\s*\($", stripped):
                in_block = True
                continue
            if stripped.startswith("package "):
                continue
            if m := re.match(r'^import\s+((?:\w+\s+)?"[^"]+")\s*$', stripped):
                imports.append(m.group(1))
                continue
        elif _IMPORT[language].match(line):
            if "__future__" not in line:  # the file's header has it, and it must come first
                imports.append(stripped)
            continue
        body.append(line)
    return imports, "\n".join(body).strip("\n")


@dataclass
class FileBuilder:
    """The translated file: the imports of the units that stayed, then those units in order."""

    language: str
    header: str = ""  # lines that always come first (Python's FastAPI app, the C++ includes...)
    tail: str = ""  # lines that always come last (Python's `__main__` guard)
    parts: list[tuple[str, list[str], str]] = field(default_factory=list)  # (unit id, imports, code)

    def add(self, unit_id: str, code: str) -> None:
        imports, body = split_imports(code, self.language)
        self.parts.append((unit_id, imports, body))

    def remove(self, unit_id: str) -> None:
        self.parts = [p for p in self.parts if p[0] != unit_id]

    def has(self, unit_id: str) -> bool:
        return any(p[0] == unit_id for p in self.parts)

    def render(self) -> str:
        imports = sorted({i for _, imps, _ in self.parts for i in imps})
        gap = "\n\n\n" if self.language == "Python" else "\n\n"
        bodies = gap.join(code for _, _, code in self.parts)
        if self.language == "Go":
            block = "import (\n" + "".join(f"\t{i}\n" for i in imports) + ")\n\n" if imports else ""
            return f"package main\n\n{block}{bodies}\n".replace("\n\n\n\n", "\n\n\n")
        top = "\n".join(imports)
        pieces = [p for p in (self.header.strip("\n"), top, bodies, self.tail.strip("\n")) if p]
        return gap.join(pieces).rstrip("\n") + "\n"


def builder_for(language: str, kind: str, package: str) -> FileBuilder:
    if language == "Python":
        if kind == "cli":
            tail = 'if __name__ == "__main__":\n    main()'
            return FileBuilder(language, "from __future__ import annotations", tail)
        header = "from __future__ import annotations\n\nfrom fastapi import FastAPI\n\napp = FastAPI()"
        return FileBuilder(language, header)
    if language == "C++":
        return FileBuilder(language)
    return FileBuilder(language)
