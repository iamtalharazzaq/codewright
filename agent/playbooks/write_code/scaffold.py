"""The smallest project each Language Pack recognizes, for Write code's throwaway workspace: fixed files (manifest,
build file) plus the two files the model writes (the solution and its tests)."""

from __future__ import annotations

import re
from dataclasses import dataclass

LANGUAGES = ("Python", "Go", "C++", "TypeScript", "JavaScript")


@dataclass(frozen=True)
class Layout:
    pack: str
    code: str  # the solution file
    tests: str  # its test file
    fixed: dict[str, str]  # files written as they are
    test_hint: str  # what the QA prompt must follow so the pack's runner finds and understands the tests
    code_hint: str


_PACKAGE = """{
  "name": "snippet",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": { "test": "vitest run" },
  "devDependencies": { "vitest": "^2.1.0"%s }
}
"""
_PYPROJECT = """[project]
name = "snippet"
version = "0.1.0"

[tool.setuptools]
py-modules = ["solution"]

[tool.pytest.ini_options]
pythonpath = ["."]
"""
_TSCONFIG = '{"compilerOptions":{"target":"ES2022","module":"ESNext","moduleResolution":"Bundler","strict":true}}\n'
_CMAKE = """cmake_minimum_required(VERSION 3.16)
project(snippet LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
enable_testing()
add_executable(snippet_tests test.cpp)
add_test(NAME snippet_tests COMMAND snippet_tests)
"""

LAYOUTS: dict[str, Layout] = {
    "Python": Layout(
        "python",
        "solution.py",
        "test_solution.py",
        {"pyproject.toml": _PYPROJECT},
        "pytest functions named test_*, importing from `solution`.",
        "Plain Python 3 with type hints, no third-party packages.",
    ),
    "Go": Layout(
        "go",
        "solution.go",
        "solution_test.go",
        {"go.mod": "module snippet\n\ngo 1.22\n"},
        "package snippet, the standard `testing` package, table-driven tests.",
        "package snippet; the standard library only.",
    ),
    "C++": Layout(
        "cpp",
        "solution.hpp",
        "test.cpp",
        {"CMakeLists.txt": _CMAKE},
        '`#include "solution.hpp"`, plain `assert` from <cassert> (no test framework), a `main` that runs every '
        "check and returns 0, printing nothing on success.",
        "A header-only C++17 file with an include guard; the standard library only.",
    ),
    "TypeScript": Layout(
        "typescript",
        "solution.ts",
        "solution.test.ts",
        {
            "package.json": _PACKAGE % ', "typescript": "^5.6.0"',
            "tsconfig.json": _TSCONFIG,
        },
        "vitest: `import { describe, it, expect } from 'vitest'`, importing from './solution' (no extension).",
        "Strict TypeScript with `export`ed functions; no packages.",
    ),
    "JavaScript": Layout(
        "javascript",
        "solution.js",
        "solution.test.js",
        {"package.json": _PACKAGE % ""},
        "vitest: `import { describe, it, expect } from 'vitest'`, importing from './solution.js'.",
        "ES modules with `export`ed functions; no packages.",
    ),
}


def layout(language: str) -> Layout:
    return LAYOUTS[language]


def slug(text: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(words.split("-")[:5]) or "snippet"
