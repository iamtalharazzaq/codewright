"""C++ pack: CMake projects, console apps and libraries (C++17/20). CMake + Ninja + g++ · CTest (GoogleTest,
Catch2) · cppcheck, clang-tidy.

Builds go to `<component>/.codewright/build`. Tests get no network; `FetchContent` of GoogleTest/Catch2 is first
satisfied from the image's installed packages (`FETCHCONTENT_TRY_FIND_PACKAGE_MODE=ALWAYS`).
"""

from __future__ import annotations

import re
from pathlib import Path

from agent.language_packs import reports, templates
from agent.language_packs.base import (
    REPORTS,
    Component,
    Contract,
    DockerSpec,
    GraphFragment,
    InstrumentationSpec,
    RunSpec,
    ServiceSpec,
    Step,
    TestReport,
    Toolchain,
    line_of,
    manifests,
    read,
    rel,
    walk,
)

BUILD = ".codewright/build"
SOURCES = (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h", ".ipp")
_PROJECT = re.compile(r"\bproject\s*\(\s*([\w.-]+)", re.IGNORECASE)
_EXECUTABLE = re.compile(r"\badd_executable\s*\(\s*([\w.-]+)", re.IGNORECASE)
_LIBRARY = re.compile(r"\badd_library\s*\(\s*([\w.-]+)", re.IGNORECASE)
_LINK = re.compile(r"\btarget_link_libraries\s*\(\s*([\w.-]+)([^)]*)\)", re.IGNORECASE | re.DOTALL)
_TEST = re.compile(
    r"\b(?:add_test\s*\(\s*(?:NAME\s+)?([\w.-]+)|gtest_discover_tests\s*\(\s*([\w.-]+)|catch_discover_tests\s*\(\s*([\w.-]+))",
    re.IGNORECASE,
)
_STANDARD = re.compile(r"CMAKE_CXX_STANDARD\s+(\d+)|cxx_std_(\d+)")
_SUBDIR = re.compile(r"\badd_subdirectory\s*\(\s*([\w./-]+)", re.IGNORECASE)
_CLASS = re.compile(r"^\s*(?:class|struct)\s+(?:\w+\s+)?([A-Z]\w*)\s*(?::[^{;]*)?\{", re.MULTILINE)


def _cmake_files(root: Path) -> list[Path]:
    """The project's CMakeLists.txt files, following add_subdirectory from the root."""
    seen: list[Path] = []
    todo = [root]
    while todo:
        folder = todo.pop(0)
        f = folder / "CMakeLists.txt"
        if not f.is_file() or f in seen:
            continue
        seen.append(f)
        for m in _SUBDIR.finditer(read(f)):
            sub = (folder / m.group(1)).resolve()
            if root.resolve() in (sub, *sub.parents):
                todo.append(folder / m.group(1))
    return seen


class CppPack:
    name = "cpp"
    language = "C++"
    toolchain: Toolchain = "cpp"

    def detect(self, repo: Path) -> list[Component]:
        components = []
        covered: set[Path] = set()
        for top in manifests(repo, "CMakeLists.txt"):
            if top in covered or not _PROJECT.search(read(top)):
                continue
            root = top.parent
            files = _cmake_files(root)
            covered.update(files)
            text = "\n".join(read(f) for f in files)
            executables: dict[str, str] = {}
            for f in files:
                for m in _EXECUTABLE.finditer(read(f)):
                    executables[m.group(1)] = rel(f.parent, root)
            tests = {next(g for g in m.groups() if g) for m in _TEST.finditer(text)}
            frameworks = []
            low = text.lower()
            if "gtest" in low or "googletest" in low:
                frameworks.append("googletest")
            if "catch2" in low:
                frameworks.append("catch2")
            if "enable_testing" in low or tests:
                frameworks.append("ctest")
            std = _STANDARD.search(text)
            programs = [e for e in executables if e not in tests and not re.search(r"test", e, re.IGNORECASE)]
            components.append(
                Component(
                    pack=self.name,
                    path=rel(root, repo),
                    kind="cli" if programs else "library",
                    frameworks=sorted(frameworks),
                    entrypoints=programs,
                    manifest="CMakeLists.txt",
                    details={
                        "project": (_PROJECT.search(read(top)) or [None, ""])[1],
                        "executables": executables,
                        "libraries": sorted({m.group(1) for m in _LIBRARY.finditer(text)}),
                        "tests": sorted(tests),
                        "standard": next((g for g in (std.groups() if std else ()) if g), ""),
                    },
                )
            )
        return components

    def parse(self, repo: Path, component: Component) -> GraphFragment:
        root = repo / component.path
        g = GraphFragment()
        for f in _cmake_files(root):
            name = rel(f, repo)
            src = read(f)
            for m in _EXECUTABLE.finditer(src):
                g.node("target", m.group(1), name, line_of(src, m.start()), type="executable")
            for m in _LIBRARY.finditer(src):
                g.node("target", m.group(1), name, line_of(src, m.start()), type="library")
            for m in _LINK.finditer(src):
                for lib in re.findall(r"[\w:.-]+", m.group(2)):
                    if lib.upper() not in {"PUBLIC", "PRIVATE", "INTERFACE"}:
                        g.edge(f"target:{m.group(1)}", f"target:{lib}", "links", 1.0)
            for m in _TEST.finditer(src):
                test = next(x for x in m.groups() if x)
                g.node("test", test, name, line_of(src, m.start()))
        for f in walk(root, SOURCES):
            src = read(f, 300_000)
            for m in _CLASS.finditer(src):
                g.node("class", m.group(1), rel(f, repo), line_of(src, m.start()))
        return g

    def _configure(self, component: Component) -> Step:
        cmd = [
            "cmake", "-S", ".", "-B", BUILD, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Debug",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", "-DFETCHCONTENT_TRY_FIND_PACKAGE_MODE=ALWAYS", "-DBUILD_TESTING=ON",
        ]  # fmt: skip
        return Step("configure", "cpp", cmd, component.path, "none")

    def build_steps(self, repo: Path, component: Component) -> list[Step]:
        return [
            self._configure(component),
            Step("build", "cpp", ["cmake", "--build", BUILD, "--parallel", "2"], component.path, "none"),
        ]

    def test_steps(self, repo: Path, component: Component) -> list[Step]:
        junit = "../reports/ctest.xml"  # relative to the test directory (BUILD)
        cmd = ["ctest", "--test-dir", BUILD, "--output-on-failure", "--no-tests=error", "--output-junit", junit]
        return [Step("test", "cpp", cmd, component.path, "none", report="junit")]

    def lint_steps(self, repo: Path, component: Component) -> list[Step]:
        cmd = ["cppcheck", "--enable=warning,performance,portability", "--error-exitcode=1", "--quiet",
               "--inline-suppr", "--suppress=missingIncludeSystem", "-i", ".codewright", "."]  # fmt: skip
        tidy = ["sh", "-c", f"[ -f {BUILD}/compile_commands.json ] && find . -path ./.codewright -prune -o "
                f"-name '*.cpp' -print | head -50 | xargs -r clang-tidy -p {BUILD} --quiet"]  # fmt: skip
        return [
            Step("cppcheck", "cpp", cmd, component.path, "none"),
            Step("clang-tidy", "cpp", tidy, component.path, "none", optional=True),
        ]

    def run_spec(self, repo: Path, component: Component) -> RunSpec | None:
        if not component.entrypoints:
            return None
        target = component.entrypoints[0]
        folder = component.details.get("executables", {}).get(target, ".")
        binary = f"{BUILD}/{target}" if folder == "." else f"{BUILD}/{folder}/{target}"
        return RunSpec(
            "terminal", "cpp", ["./" + binary], component.path, prepare=self.build_steps(repo, component), name=target
        )

    def read_report(self, repo: Path, component: Component, step: Step, output: str) -> TestReport:
        return reports.junit([repo / component.path / REPORTS / "ctest.xml"], "ctest")

    def scaffold_service(self, spec: ServiceSpec, out: Path) -> None:
        templates.scaffold(spec, out)

    def client_stub(self, contract: Contract, out: Path) -> Path:
        """A header declaring one function per endpoint over a caller-supplied HTTP transport (no dependency)."""
        ns = re.sub(r"\W", "_", contract.service.lower())
        lines = [
            f"// Client for the {contract.service} API. Generated by Codewright; edit freely.",
            "#pragma once",
            "#include <functional>",
            "#include <string>",
            "",
            f"namespace {ns} {{",
            "",
            "// method, path, JSON body → JSON response. Plug in libcurl, cpp-httplib or a test fake.",
            "using Transport = std::function<std::string(const std::string&, const std::string&, const std::string&)>;",
            "",
            "class Client {",
            " public:",
            "  explicit Client(Transport transport) : transport_(std::move(transport)) {}",
        ]
        for ep in contract.endpoints:
            params = re.findall(r"\{(\w+)\}", ep.path)
            args = [f"const std::string& {p}" for p in params] + (["const std::string& body"] if ep.request else [])
            expr = '"' + re.sub(r"\{(\w+)\}", r'" + \1 + "', ep.path) + '"'
            expr = expr.replace(' + ""', "")
            lines += [
                f"  // {ep.method} {ep.path}",
                f"  std::string {ep.name}({', '.join(args)}) const {{",
                f'    return transport_("{ep.method}", {expr}, {"body" if ep.request else '""'});',
                "  }",
            ]
        lines += [" private:", "  Transport transport_;", "};", "", f"}}  // namespace {ns}"]
        path = out / f"{ns}_client.hpp"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def docker_base(self) -> DockerSpec:
        return DockerSpec(
            "cpp",
            "debian:bookworm-slim",
            "FROM debian:bookworm-slim AS build\nRUN apt-get update && apt-get install -y --no-install-recommends "
            "build-essential cmake ninja-build && rm -rf /var/lib/apt/lists/*\nWORKDIR /src\nCOPY . .\n"
            "RUN cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build\n\n"
            "FROM debian:bookworm-slim\nCOPY --from=build /src/build/{name} /usr/local/bin/{name}\n"
            'RUN useradd --system --uid 10001 app\nUSER app\nENTRYPOINT ["/usr/local/bin/{name}"]\n',
        )

    def instrumentation(self) -> InstrumentationSpec:
        return InstrumentationSpec(
            packages=["opentelemetry-cpp (CMake: find_package(opentelemetry-cpp CONFIG))"],
            env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://jaeger:4317", "OTEL_SERVICE_NAME": "{name}"},
            notes="Link opentelemetry-cpp::trace and an OTLP exporter; console apps rarely need tracing.",
        )
