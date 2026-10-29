"""Black-box cases for a terminal app (CODEWRIGHT.md Section 5.16 step 1: "contract + black-box tests"): invocations
(arguments + standard input) run on the **original** program, whose exit code and output become the expectation, then
run the same way on the translation. The cases do not depend on the language, so the very same ones judge both.

Nothing here knows how a program is built: the Language Pack's `RunSpec` (prepare steps, command, folder) says how
to start it, and `ProjectTools.run_step` runs it in the sandbox.
"""

from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass
from typing import Any

from agent.language_packs.base import RunSpec, Step
from agent.playbooks.services import ProjectTools

UNSTABLE = ("Traceback (most recent call last)", "panic:", "Segmentation fault", "core dumped", "terminate called",
            "Exception in thread", "UnhandledPromiseRejection", "goroutine ")  # fmt: skip
MAX_CASES = 10
TIMEOUT_S = 60


@dataclass
class Case:
    name: str
    args: list[str]
    stdin: str = ""
    exit_code: int = 0
    output: str = ""  # what the original printed (stdout and stderr together, as the sandbox returns it)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize(text: str) -> str:
    """Trailing spaces and blank edges don't count as a difference."""
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def name_of(args: list[str], stdin: str) -> str:
    shown = " ".join(args) or "(no arguments)"
    return shown + (" < stdin" if stdin else "")


def step_for(spec: RunSpec, args: list[str], stdin: str = "") -> Step:
    """One invocation as a sandbox step. Standard input goes through `sh -c` (printf into a pipe)."""
    base = [*spec.cmd, *args]
    cmd = ["sh", "-c", f"printf %s {shlex.quote(stdin)} | {shlex.join(base)}"] if stdin else base
    return Step("blackbox", spec.toolchain, cmd, spec.workdir, network="none", timeout_s=TIMEOUT_S, env=dict(spec.env))


async def prepare(project: ProjectTools, spec: RunSpec) -> str:
    """Run the install/build steps the program needs first. '' = ready, else why it is not."""
    for step in spec.prepare:
        done = await project.run_step(step)
        if not done.get("ok"):
            return f"{step.name} failed: {str(done.get('output', ''))[-400:]}"
    return ""


async def run(project: ProjectTools, spec: RunSpec, args: list[str], stdin: str = "") -> dict[str, Any]:
    done = await project.run_step(step_for(spec, args, stdin))
    return {"exit_code": done.get("exit_code"), "output": str(done.get("output", ""))}


def stable(result: dict[str, Any]) -> bool:
    """A crash prints a language-specific trace, so it is not a behavior to reproduce; so is a command that hangs."""
    code = result["exit_code"]
    return code is not None and 0 <= code <= 2 and not any(m in result["output"] for m in UNSTABLE)


async def capture(
    project: ProjectTools, spec: RunSpec, proposals: list[tuple[list[str], str]]
) -> tuple[list[Case], list[str]]:
    """Run each proposed invocation on the original. Returns the stable cases and a note for each one left out."""
    cases: list[Case] = []
    skipped: list[str] = []
    seen: set[tuple[tuple[str, ...], str]] = set()
    for args, stdin in proposals:
        key = (tuple(args), stdin)
        if key in seen or len(cases) >= MAX_CASES:
            continue
        seen.add(key)
        result = await run(project, spec, args, stdin)
        if stable(result):
            cases.append(Case(name_of(args, stdin), args, stdin, int(result["exit_code"]), result["output"]))
        else:
            skipped.append(f"{name_of(args, stdin)}: crashed or hung on the original, so not a behavior to copy")
    return cases, skipped


async def check(project: ProjectTools, spec: RunSpec, cases: list[Case]) -> list[dict[str, Any]]:
    """The same cases on the translation: one result per case, `ok` or what differed."""
    results: list[dict[str, Any]] = []
    for case in cases:
        got = await run(project, spec, case.args, case.stdin)
        ok = got["exit_code"] == case.exit_code and normalize(got["output"]) == normalize(case.output)
        results.append(
            {
                "name": case.name,
                "ok": ok,
                "expected": {"exit_code": case.exit_code, "output": case.output[-600:]},
                "got": {"exit_code": got["exit_code"], "output": got["output"][-600:]},
            }
        )
    return results


def failure_text(results: list[dict[str, Any]], limit: int = 3) -> str:
    """The failing cases as feedback for the model that has to fix the translation."""
    bad = [r for r in results if not r["ok"]][:limit]
    return "\n\n".join(
        f"Run with: {r['name']}\nExpected (exit {r['expected']['exit_code']}):\n{r['expected']['output']}\n"
        f"Got (exit {r['got']['exit_code']}):\n{r['got']['output']}"
        for r in bad
    )[:2400]
