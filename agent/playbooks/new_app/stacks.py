"""Which language, stack and template a new app gets (CODEWRIGHT.md Section 5.17): rules, no model.

The app type decides which stacks are offered (recommended first); the user's answer always wins; only the five
supported languages are built. Templates are preferred because they give a 9B model the most reliable start: a stack
whose template is missing falls back to the closest template that exists, and the report says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.language_packs import templates

SIZES = ("small", "medium", "large")
TIER_OF = {"small": 1, "medium": 2, "large": 3}
UNSUPPORTED = ("rust", "java", "c#", "csharp", "ruby", "php", "swift", "kotlin", "scala", "dart", "elixir")


@dataclass(frozen=True)
class Option:
    label: str
    template: str


@dataclass(frozen=True)
class AppKind:
    name: str
    why: str  # why the first option is recommended
    options: tuple[Option, ...]  # recommended first


KINDS: dict[str, AppKind] = {k.name: k for k in (
    AppKind("browser", "it runs in the browser, so you can play it in Preview", (
        Option("TypeScript + React", "web-react-ts"), Option("JavaScript + React", "web-react-js"),
        Option("Python (terminal)", "cli-python"), Option("Go (terminal)", "cli-go"),
        Option("C++ (terminal)", "cli-cpp"),
    )),
    AppKind("site", "Next.js pages are fast and good for search engines", (
        Option("Next.js (TypeScript)", "site-nextjs-ts"), Option("Next.js (JavaScript)", "site-nextjs-js"),
    )),
    AppKind("webapp", "FastAPI is quick to write and Next.js gives a modern interface", (
        Option("Next.js + Python (FastAPI)", "fullstack-fastapi-nextjs"), Option("Next.js + Go", "fullstack-go-nextjs"),
        Option("Next.js + Node (TypeScript)", "fullstack-node-nextjs"),
    )),
    AppKind("api", "Go is small, fast and easy to deploy", (
        Option("Go", "api-go"), Option("Python (FastAPI)", "api-fastapi"), Option("TypeScript (Node)", "api-node"),
    )),
    AppKind("cli", "Python is the quickest to write and read", (
        Option("Python", "cli-python"), Option("Go", "cli-go"), Option("C++", "cli-cpp"),
    )),
    AppKind("systems", "C++ gives the most control over speed and memory", (
        Option("C++", "cli-cpp"), Option("Go", "cli-go"),
    )),
    AppKind("library", "Python packages are the easiest to share", (
        Option("Python", "library-python"), Option("TypeScript", "library-ts"), Option("Go", "library-go"),
        Option("C++", "library-cpp"),
    )),
    AppKind("function", "A single file is the simplest thing to copy into your own code", (
        Option("Python", "function-python"), Option("TypeScript", "function-ts"), Option("Go", "function-go"),
    )),
    AppKind("script", "Python has a library for almost every task", (Option("Python", "cli-python"),)),
)}  # fmt: skip

# (kind, words in the request); the first match wins, so the more specific kinds come first.
# Not "users": the requirements Q&A text almost always contains it (e.g. the model's own answer to "who is the
# main user?"), so it drowned out a real signal like "terminal" below. "multi-user" still counts.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("function", ("pure function", "single function", "just a function", "only a function", "just functions",
                  "functions only", "one function", "no library", "without any library", "without a library",
                  "without library")),
    ("library", ("library", "package", "sdk", "module for")),
    ("systems", ("algorithm", "performance-critical", "systems-level", "high-performance", "low-level")),
    ("script", ("script", "automation", "automate", "scrape", "csv", "data processing", "rename files")),
    ("api", ("rest api", " api", "backend service", "microservice", "endpoint", "webhook")),
    ("webapp", ("login", "sign in", "database", "inventory", "booking", "appointment", "shop", "store",
                "marketplace", "dashboard", "admin", "crm", "payments", "orders", "clinic", "multi-user")),
    ("site", ("landing page", "website", "portfolio", "marketing page", "blog")),
    ("cli", ("terminal", "cli", "command line", "console", "text adventure")),
)  # fmt: skip
_LARGE = ("marketplace", "payments", "clinic", "multi-user", "multi user", "booking system", "erp", "crm", "hospital")
_MEDIUM = ("inventory", "blog", "booking", "shop", "store", "login", "database", "admin", "dashboard", "api")

_LANG_WORDS: tuple[tuple[str, str], ...] = (
    ("typescript", "TypeScript"), (" ts ", "TypeScript"), ("javascript", "JavaScript"), (" js ", "JavaScript"),
    ("python", "Python"), ("fastapi", "Python"), ("golang", "Go"), (" go ", "Go"), ("c++", "C++"), ("cpp", "C++"),
    ("node", "TypeScript"), ("next", "TypeScript"), ("react", "TypeScript"),
)  # fmt: skip


def _text(inputs: dict[str, Any]) -> str:
    card = inputs.get("card") or {}
    parts = [str(inputs.get("request", "")), str(inputs.get("stack", "")), str(inputs.get("language", ""))]
    parts += [str(card.get(k, "")) for k in ("what", "stack", "platform", "features")]
    parts += [str(a[1]) for a in inputs.get("answers", []) if isinstance(a, list | tuple) and len(a) == 2]
    return " " + " ".join(parts).lower() + " "


def _has(text: str, words: tuple[str, ...]) -> bool:
    """Whole words only ('script' is not in 'javascript'); a trailing plural 's' is allowed."""
    return any(re.search(rf"\b{re.escape(w.strip())}s?\b", text) for w in words)


def app_kind(inputs: dict[str, Any]) -> str:
    """The kind of app: browser tool/game (the default), site, web app with data, API, CLI, library, script..."""
    text = _text(inputs)
    for kind, words in _RULES:
        if _has(text, words):
            return kind
    return "browser"


def size_of(inputs: dict[str, Any]) -> str:
    """small / medium / large: the confirmed size, else judged from the words of the request."""
    given = str(inputs.get("size") or "").lower()
    if given in SIZES:
        return given
    text = _text(inputs)
    if _has(text, _LARGE):
        return "large"
    return "medium" if _has(text, _MEDIUM) else "small"


def named_language(inputs: dict[str, Any]) -> str:
    """The language the user named in the language/stack fields or the answers ('' = none named)."""
    said = answer_to(inputs, "Which language?")
    if said:  # an answer to the language question beats words that happen to appear in other answers
        for word, lang in _LANG_WORDS:
            if word in " " + said.lower() + " ":
                return lang
    explicit = " " + " ".join(
        [
            str(inputs.get("language", "")),
            str(inputs.get("stack", "")),
            str((inputs.get("card") or {}).get("stack", "")),
        ]
        + [str(a[1]) for a in inputs.get("answers", []) if isinstance(a, list | tuple) and len(a) == 2]
    ).lower() + " "  # fmt: skip
    for word, lang in _LANG_WORDS:
        if word in explicit:
            return lang
    return ""


def unsupported_language(inputs: dict[str, Any]) -> str:
    text = _text(inputs)
    return next((u for u in UNSUPPORTED if re.search(rf"(?<![a-z]){re.escape(u)}(?![a-z+#])", text)), "")


def options_text(kind: str) -> str:
    """The choice shown in the missing-info message: options that fit the app type, one recommended with a reason."""
    k = KINDS[kind]
    lines = [f"- **{o.label}**" + (f" (recommended: {k.why})" if i == 0 else "") for i, o in enumerate(k.options)]
    return "Which language should I use?\n" + "\n".join(lines)


def _language_of(option: Option) -> str:
    label = option.label
    for word, lang in (("JavaScript", "JavaScript"), ("TypeScript", "TypeScript"), ("Node", "TypeScript"),
                       ("Python", "Python"), ("C++", "C++"), ("Go", "Go")):  # fmt: skip
        if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", label):
            return lang
    return ""


def _pick(kind: AppKind, language: str) -> Option:
    """The first option in the user's language, else the recommended one."""
    return next((o for o in kind.options if language and _language_of(o) == language), kind.options[0])


@dataclass(frozen=True)
class Choice:
    kind: str
    size: str
    template: str
    label: str
    language: str
    note: str = ""  # why the choice differs from what was asked (an unsupported language, a missing template)


def choose(inputs: dict[str, Any], root: Any = templates.ROOT) -> Choice:
    kind_name = app_kind(inputs)
    size = size_of(inputs)
    language = named_language(inputs)
    note = ""
    if blocked := unsupported_language(inputs):
        note = (
            f"{blocked.capitalize()} isn't one of the five supported languages, so the closest supported stack is used."
        )
        language = ""
    kind = KINDS[kind_name]
    option = _pick(kind, language)
    have = {t.name: t for t in templates.available(root)}
    chosen = (answer_to(inputs, FRONTEND_QUESTION) or "").lower()
    if kind_name == "browser" and chosen:
        template = _FRONTEND_TEMPLATE.get(chosen)  # "None": no browser code, so the terminal pick above stays
        if template in have:
            option = Option(have[template].name, template)
            if language and have[template].language != language:
                got = have[template].language
                note = (
                    note + " " if note else ""
                ) + f"The frontend you chose is {got}, so the app is {got}, not {language}."
            language = ""  # the chosen frontend decides; no "no browser template" note below
    if option.template not in have:
        fallback = next((o for o in kind.options if o.template in have), None)
        if fallback is None:
            raise LookupError(f"No template is available for {option.label}.")
        note = (note + " " if note else "") + (
            f"The {option.label} template isn't in the library yet, so {fallback.label} is used."
        )
        option = fallback
    if kind_name == "browser" and option.template.startswith("cli-") and language:
        note = (note + " " if note else "") + (
            f"There is no browser template for {language}, so this is a terminal app. "
            "Choose TypeScript or JavaScript for one that runs in the browser."
        )
    return Choice(kind_name, size, option.template, option.label, have[option.template].language, note)


# ── extras the user has to ask for ───────────────────────────────────────────
_CI_WORDS = ("ci", "github actions", "continuous integration", "pipeline")
_TEST_WORDS = ("test", "testing", "unit test", "vitest", "jest", "tdd")


@dataclass(frozen=True)
class Extras:
    """What a new app only gets when the user asked: a CI workflow, the Graphify setup, tests for the browser code."""

    ci: bool = False
    graphify: bool = False
    frontend_tests: bool = False
    backend_tests: bool = True
    readme: bool = False


def _asked(inputs: dict[str, Any]) -> str:
    """What the user said (the request and the answers to questions), not what the model drafted."""
    answers = [str(a[1]) for a in inputs.get("answers", []) if isinstance(a, list | tuple) and len(a) == 2]
    return " " + " ".join([str(inputs.get("request", "")), *answers]).lower() + " "


def answer_to(inputs: dict[str, Any], question: str) -> str | None:
    """The user's answer to `question`: the chat sends all answers as one reply, a line per question
    ("Which platform? Terminal"); a (question, reply) pair for just that question works too. None if unanswered."""
    for pair in inputs.get("answers", []):
        if not (isinstance(pair, list | tuple) and len(pair) == 2):
            continue
        if pair[0] == question:
            return str(pair[1]).strip()
        for line in str(pair[1]).splitlines():
            if line.strip().startswith(question):
                return line.strip()[len(question) :].strip()
    return None


def extras(inputs: dict[str, Any]) -> Extras:
    text = _asked(inputs)
    extra = answer_to(inputs, ADDITIONS_QUESTION)
    if extra is not None:  # the ticked boxes, e.g. "README file, Test cases (backend)"
        ticked = extra.lower()
        return Extras(
            ci=CI.lower() in ticked,
            graphify=GRAPHIFY.lower() in ticked,
            frontend_tests=FRONTEND_TESTS.lower() in ticked,
            backend_tests=BACKEND_TESTS.lower() in ticked,
            readme=README.lower() in ticked,
        )
    return Extras(  # not asked yet (or a run started without the card): only what the request says
        ci=_has(text, _CI_WORDS),
        graphify=_has(text, ("graphify",)),
        frontend_tests=_has(text, _TEST_WORDS),
        readme=_has(text, ("readme",)),
    )


def deliver_text(inputs: dict[str, Any]) -> str:
    """What the user gets, from what was ticked: the card must not promise what they declined."""
    wanted = extras(inputs)
    parts = ["a working app in Preview"]
    if wanted.backend_tests or wanted.frontend_tests:
        parts.append("tests")
    parts.append("GUIDE.md")
    if wanted.readme:
        parts.append("a README")
    if wanted.ci:
        parts.append("a CI workflow")
    if wanted.graphify:
        parts.append("the Graphify setup")
    text = ", ".join(parts[:-1]) + f", {parts[-1]} and a Done card" if len(parts) > 1 else parts[0]
    return text[0].upper() + text[1:]


def additions_default(request: str) -> str:
    """The boxes ticked at first: the backend's tests, plus whatever the request already asks for."""
    wanted = extras({"request": request})
    ticked = [
        name
        for name, on in (
            (CI, wanted.ci),
            (README, wanted.readme),
            (GRAPHIFY, wanted.graphify),
            (BACKEND_TESTS, True),
            (FRONTEND_TESTS, wanted.frontend_tests),
        )
        if on
    ]
    return ", ".join(ticked)


def expects_tests(template: str, wanted: Extras) -> bool:
    """Whether the built app should have tests: its backend's (terminal, API and full-stack apps) or its browser
    code's, each only when asked for."""
    top = templates.frontend_root(template)
    return (top != "" and wanted.backend_tests) or (top is not None and wanted.frontend_tests)


FRONTEND_QUESTION = "Which frontend?"
FRONTENDS = ("React + TypeScript", "React + JavaScript", "Next.js (TypeScript)", "Next.js (JavaScript)", "None")
_FRONTEND_TEMPLATE = {
    "react + typescript": "web-react-ts", "react + javascript": "web-react-js",
    "next.js (typescript)": "site-nextjs-ts", "next.js (javascript)": "site-nextjs-js",
}  # fmt: skip
ADDITIONS_QUESTION = "Additional things to be added"
CI = "CI workflow (GitHub Actions)"
README, GRAPHIFY = "README file", "Graphify"
BACKEND_TESTS, FRONTEND_TESTS = "Test cases (backend)", "Test cases (frontend)"
ADDITIONS = (CI, README, GRAPHIFY, BACKEND_TESTS, FRONTEND_TESTS)
_NO_UI_WORDS = (
    "terminal",
    "cli",
    "command line",
    "console",
    "api",
    "rest api",
    "library",
    "functions only",
    "just a function",
    "only a function",
    "just functions",
)


def frontend_open(inputs: dict[str, Any]) -> bool:
    """Whether to ask which frontend: not once answered, nor for a stated terminal/API app."""
    return answer_to(inputs, FRONTEND_QUESTION) is None and not _has(_asked(inputs), _NO_UI_WORDS)


def frontend_default(language: str) -> str:
    return FRONTENDS[1] if language == "JavaScript" else FRONTENDS[0]


PLATFORM_QUESTION = "Which platform?"
PLATFORMS = ("Browser app", "Terminal (command line)", "API (REST)", "Just a function (one file, no library)")
_PLATFORM_WORDS = ("browser", "web", "website", "terminal", "cli", "command line", "console", "api", "rest api",
                   "library", "functions only", "no library", "without any library", "without a library",
                   "just a function", "only a function", "just functions", "pure function",
                   "single function")  # fmt: skip


def platform_stated(inputs: dict[str, Any]) -> bool:
    """Whether the user already said where the app runs: in the request, or as an answer to the platform question."""
    if answer_to(inputs, PLATFORM_QUESTION) is not None:
        return True
    return _has(_asked(inputs), _PLATFORM_WORDS)


def default_platform(inputs: dict[str, Any]) -> str:
    """The platform the rules would pick for this request: the question's default."""
    kind = app_kind({"request": inputs.get("request", "")})
    return {
        "cli": PLATFORMS[1],
        "script": PLATFORMS[1],
        "systems": PLATFORMS[1],
        "api": PLATFORMS[2],
        "function": PLATFORMS[3],
    }.get(kind, PLATFORMS[0])
