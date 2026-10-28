"""Noise rules (CODEWRIGHT.md Section 5.18, behavior verification): differences between two answers that aren't a
change in behavior: generated IDs, timestamps, tokens, float rounding, array order.

The built-in rules hold for any app; a project can switch one off or add its own (a JSON path pattern and what to
do there). Every rule says why it exists, and every difference it explains names it, so the user sees what was
ignored and can disagree.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

RuleKind = Literal["ignore", "id", "timestamp", "token", "tolerance", "unordered"]

UUID = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
OBJECT_ID = re.compile(r"^[0-9a-f]{24}$")
JWT = re.compile(r"^(Bearer )?eyJ[\w-]+\.eyJ[\w-]+\.[\w-]+$")
ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
HTTP_DATE = re.compile(r"^[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT$")
TIME_KEY = re.compile(
    r"(^|[_.-])(at|time|date|timestamp|ts|expires?|exp|iat|nbf|updated|created|deleted)$|(At|Time|Date)$"
)
TOKEN_KEY = re.compile(r"(token|secret|nonce|signature|csrf|session|salt|hash)", re.I)
ID_KEY = re.compile(r"(^id$|_id$|Id$|^uuid$|_uuid$|^key$)")
EPOCH_MIN = 1e8
RANDOM_TOKEN = re.compile(r"^[A-Za-z0-9+/_=-]{24,}$")
# In text bodies (HTML, plain text): values masked before comparing.
TEXT_MASKS = [
    (re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"), "<uuid>"),
    (re.compile(r"eyJ[\w-]+\.eyJ[\w-]+\.[\w-]+"), "<jwt>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?"), "<time>"),
]
# Response headers that change on every answer.
VOLATILE_HEADERS = [
    "date", "etag", "set-cookie", "x-request-id", "request-id", "x-correlation-id", "traceparent", "last-modified",
    "expires", "age", "server-timing", "x-response-time", "content-length",
]  # fmt: skip
COMPARED_HEADERS = ["content-type", "location", "content-disposition", "www-authenticate", "cache-control"]


@dataclass
class Rule:
    id: str
    kind: RuleKind
    description: str
    where: str = "**"  # JSON path pattern: $.data[*].created_at, **.updated_at (fnmatch; [*] is any index)
    tolerance: float = 0.0
    enabled: bool = True
    builtin: bool = False

    def applies(self, path: str) -> bool:
        if not self.enabled:
            return False
        if self.where in ("**", "*"):
            return True
        return bool(glob(self.where).fullmatch(generic(path)))


BUILTIN: list[Rule] = [
    Rule("generated-ids", "id", "Generated IDs (UUID, ULID, ObjectId) differ on every run; the same kind of ID on both "
         "sides is not a change.", builtin=True),
    Rule("linked-values", "id", "A value the app gave earlier in the same journey (an ID, a token), sent back by the "
         "replay: the new run's value stands in for the recorded one.", builtin=True),
    Rule("timestamps", "timestamp", "Times (ISO 8601, HTTP dates, epoch numbers under time-like names) are when the "
         "request ran, not what it did.", builtin=True),
    Rule("tokens", "token", "Tokens, signatures and secrets (JWTs, long random strings under token-like names) are "
         "new on every login.", builtin=True),
    Rule("float-rounding", "tolerance", "Numbers within 1e-9 (relative) of each other are equal.", tolerance=1e-9,
         builtin=True),
    Rule("array-order", "unordered", "Arrays with the same items in another order. Off by default: order is "
         "behavior for sorted lists. Switch it on where the app doesn't promise an order.", enabled=False,
         builtin=True),
    Rule("volatile-headers", "ignore", "Headers that change on every answer: " + ", ".join(VOLATILE_HEADERS) + ".",
         where="header:*", builtin=True),
]  # fmt: skip


@lru_cache(maxsize=256)
def glob(pattern: str) -> re.Pattern[str]:
    """`**` is anything, `*` is one name, `[*]` is any index: `**.created_at`, `$.data[*].id`, `header:*`."""
    out = re.escape(generic(pattern.replace("[*]", "[0]")))
    out = out.replace(r"\*\*", ".*").replace(r"\*", r"[^.\[\]]*")
    return re.compile(("" if pattern.startswith(("$", "**", "header:")) else r"(?:.*\.)?") + out)


def generic(path: str) -> str:
    """$.items[3].id → $.items[#].id: array indexes don't matter to a rule."""
    return re.sub(r"\[\d+\]", "[#]", path)


@dataclass
class NoiseRules:
    rules: list[Rule] = field(default_factory=lambda: [Rule(**asdict(r)) for r in BUILTIN])

    @classmethod
    def load(cls, path: Path) -> NoiseRules:
        """Built-ins (with the project's on/off choices) plus the project's own rules."""
        out = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except ValueError:
            data = {}
        disabled = set(data.get("disabled", []))
        enabled = set(data.get("enabled", []))
        for r in out.rules:
            r.enabled = (r.enabled or r.id in enabled) and r.id not in disabled
        for raw in data.get("rules", []):
            try:
                out.rules.append(Rule(**{**raw, "builtin": False}))
            except TypeError:
                continue
        return out

    def save(self, path: Path) -> None:
        defaults = {r.id: r.enabled for r in BUILTIN}
        data = {
            "disabled": [r.id for r in self.rules if r.builtin and defaults.get(r.id) and not r.enabled],
            "enabled": [r.id for r in self.rules if r.builtin and not defaults.get(r.id) and r.enabled],
            "rules": [{k: v for k, v in asdict(r).items() if k != "builtin"} for r in self.rules if not r.builtin],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def as_list(self) -> list[dict[str, Any]]:
        return [asdict(r) for r in self.rules]

    def enabled(self, rule_id: str) -> bool:
        return any(r.id == rule_id and r.enabled for r in self.rules)

    def _of(self, kind: RuleKind, path: str) -> Rule | None:
        return next((r for r in self.rules if r.kind == kind and r.applies(path)), None)

    def unordered(self, path: str) -> Rule | None:
        return self._of("unordered", path)

    def header_ignored(self, name: str) -> Rule | None:
        rule = next((r for r in self.rules if r.kind == "ignore" and r.applies(f"header:{name}")), None)
        if rule and rule.id == "volatile-headers" and name not in VOLATILE_HEADERS:
            return None
        return rule

    def explain(self, path: str, before: Any, after: Any) -> Rule | None:
        """The rule that makes this difference noise, or None (then it is a change)."""
        key = path.rsplit(".", 1)[-1].split("[", 1)[0]
        for rule in self.rules:
            if not rule.applies(path):
                continue
            if rule.kind == "ignore":
                return rule
            if rule.kind == "tolerance" and _numbers(before, after) and _close(before, after, rule.tolerance):
                return rule
            if rule.kind == "timestamp" and _timestamps(key, before, after):
                return rule
            if rule.kind == "token" and _tokens(key, before, after):
                return rule
            if rule.id == "generated-ids" and _same_id_kind(before, after):
                return rule
        return None

    def mask_text(self, text: str) -> str:
        if not any(r.enabled and r.kind in ("id", "timestamp", "token") for r in self.rules):
            return text
        for pattern, label in TEXT_MASKS:
            text = pattern.sub(label, text)
        return text


def _numbers(a: Any, b: Any) -> bool:
    return isinstance(a, int | float) and isinstance(b, int | float) and not isinstance(a, bool | type(None))


def _close(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance * max(abs(a), abs(b), 1.0)


def _timestamps(key: str, a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return bool((ISO_TIME.match(a) or HTTP_DATE.match(a)) and (ISO_TIME.match(b) or HTTP_DATE.match(b)))
    if _numbers(a, b) and TIME_KEY.search(key):
        return bool(a > EPOCH_MIN and b > EPOCH_MIN)  # epoch seconds or millis, not a small count
    return False


def _tokens(key: str, a: Any, b: Any) -> bool:
    if not (isinstance(a, str) and isinstance(b, str)):
        return False
    if JWT.match(a) and JWT.match(b):
        return True
    return bool(TOKEN_KEY.search(key)) and bool(RANDOM_TOKEN.match(a) and RANDOM_TOKEN.match(b))


def _same_id_kind(a: Any, b: Any) -> bool:
    if not (isinstance(a, str) and isinstance(b, str)):
        return False
    return any(p.match(a) and p.match(b) for p in (UUID, ULID, OBJECT_ID))
