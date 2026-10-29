# ruff: noqa: E501
"""Foundation files, scheduling and the Python extraction with its anti-corruption layer, on a small real project.

The generated shim and runtime are executed for real (in a subprocess); the service's side is a stdlib server that
follows the same contract as the generated FastAPI router, because the host test environment has no FastAPI.
"""

from __future__ import annotations

import json
import py_compile
import subprocess
import sys
import textwrap
from pathlib import Path

from agent.decomposition import boundaries as b
from agent.microservices import extract as ex
from agent.microservices import foundation as fd
from agent.microservices import schedule

DESIGN = {
    "groups": [
        {"name": "frontend", "kind": "frontend", "modules": ["web"], "tables": [], "calls": ["order"], "called_by": []},
        {
            "name": "order",
            "kind": "backend",
            "modules": ["shop/order"],
            "tables": ["orders"],
            "calls": ["payment", "notification"],
            "called_by": ["frontend"],
        },
        {
            "name": "payment",
            "kind": "backend",
            "modules": ["shop/payment"],
            "tables": ["payments"],
            "calls": ["notification"],
            "called_by": ["order"],
        },
        {
            "name": "notification",
            "kind": "backend",
            "modules": ["shop/notification"],
            "tables": [],
            "calls": [],
            "called_by": ["order", "payment"],
        },
    ]
}
PLATFORM = {"broker": "NATS", "events": [], "sagas": [], "gateway": {"routes": ["order"]}}
LANGS = {"order": "Go", "payment": "Python", "notification": "TypeScript"}

SHOP = {
    "shop/__init__.py": "",
    "shop/util/__init__.py": "",
    "shop/util/money.py": "def cents(x):\n    return round(x * 100)\n",
    "shop/payment/__init__.py": "",
    "shop/payment/gateway.py": "from shop.util.money import cents\n\n\ndef fee(amount):\n    return cents(amount) // 100\n",
    "shop/payment/service.py": (
        "from shop.payment.gateway import fee\n\n\ndef charge(amount, currency='EUR'):\n"
        "    return {'charged': amount + fee(amount), 'currency': currency}\n\n\nasync def refund(amount):\n"
        "    return {'refunded': amount}\n"
    ),
    "shop/order/__init__.py": "",
    "shop/order/checkout.py": (
        "from shop.payment import service\nfrom shop.payment.service import refund\n\n\n"
        "def place(amount):\n    return service.charge(amount, currency='USD')\n"
    ),
}
RULES = {"modules": {"payment": ["shop/payment"], "order": ["shop/order"], "util": ["shop/util"]}}


def project(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


def run(code: str, cwd: Path, **env: str) -> subprocess.CompletedProcess[str]:
    import os  # noqa: PLC0415

    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(cwd), **env},
    )


# ── foundation ───────────────────────────────────────────────────────────────
def test_the_foundation_routes_everything_to_the_monolith_until_a_cutover() -> None:
    files = fd.foundation_files(DESIGN, PLATFORM, LANGS, "Shop")
    routes = json.loads(files["gateway/routes.json"])
    assert routes["default"] == "monolith" and not any(r["live"] for r in routes["services"].values())
    assert "location /payment/" not in files["gateway/nginx.conf"]
    live = fd.render_nginx(fd.routes_for(DESIGN, {"payment": True}))
    assert "location /payment/" in live and "location /notification/" not in live
    assert (
        "libs/events/envelope.py" in files and "libs/events/envelope.go" in files and "libs/auth/jwt_hs256.ts" in files
    )
    assert fd.check_foundation(files) == []


def test_the_static_checks_find_unpinned_images_literal_secrets_and_missing_services() -> None:
    files = fd.foundation_files(DESIGN, PLATFORM, LANGS, "Shop")
    bad = dict(files)
    bad["platform/docker-compose.yml"] = (
        files["platform/docker-compose.yml"]
        .replace("nats:2.10-alpine", "nats")
        .replace("${JWT_SECRET:?set JWT_SECRET}", "hunter2")
    )
    problems = " ".join(fd.check_foundation(bad))
    assert "not pinned" in problems and "JWT_SECRET has a literal value" in problems


def test_the_jwt_and_envelope_libraries_work(tmp_path: Path) -> None:
    files = fd.foundation_files(DESIGN, PLATFORM, {"payment": "Python"}, "Shop")
    fd.write_files(tmp_path, files)
    code = textwrap.dedent(
        """
        import base64, hashlib, hmac, json, time
        from libs.auth.jwt_hs256 import verify
        from libs.events.envelope import envelope, validate

        def b64(x): return base64.urlsafe_b64encode(x).rstrip(b"=").decode()
        def token(claims, secret):
            head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
            body = b64(json.dumps(claims).encode())
            sig = b64(hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
            return f"{head}.{body}.{sig}"

        assert verify(token({"sub": "u1"}, "s"), "s")["sub"] == "u1"
        for bad in (token({"sub": "u1"}, "other"), token({"exp": time.time() - 5}, "s"), "nonsense"):
            try:
                verify(bad, "s")
            except ValueError:
                pass
            else:
                raise SystemExit("accepted " + bad)
        e = envelope("order.placed", "order", {"id": 1}); validate(e)
        try:
            validate({"id": "x"})
        except ValueError:
            print("ok")
        """
    )
    (tmp_path / "libs/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "libs/auth/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "libs/events/__init__.py").write_text("", encoding="utf-8")
    done = run(code, tmp_path)
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr


def test_existing_files_are_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / "gateway").mkdir()
    (tmp_path / "gateway/nginx.conf").write_text("mine", encoding="utf-8")
    written = fd.write_files(tmp_path, fd.foundation_files(DESIGN, PLATFORM, LANGS, "Shop"))
    assert "gateway/nginx.conf" not in written and (tmp_path / "gateway/nginx.conf").read_text() == "mine"


# ── scheduling ───────────────────────────────────────────────────────────────
def test_callees_are_built_before_their_callers_and_independent_services_share_a_wave() -> None:
    assert schedule.order(DESIGN) == ["notification", "payment", "order"]
    wide = {
        "groups": [
            {"name": n, "kind": "backend", "modules": [n], "tables": [], "calls": [], "called_by": []}
            for n in ("a", "b", "c")
        ]
    }
    assert schedule.waves(wide, max_parallel=2) == [["a", "b"], ["c"]]
    assert schedule.waves(wide, max_parallel=1) == [["a"], ["b"], ["c"]]


# ── extraction ───────────────────────────────────────────────────────────────
def test_the_plan_finds_what_the_monolith_uses_and_what_is_shared(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    plan = ex.plan_extraction(work, RULES, "payment", frozenset({"util"}))
    assert plan.blocked == ""
    assert plan.entries == {"shop/payment/service.py": ["charge", "refund"]}
    assert plan.is_async == {"shop/payment/service.py": ["refund"]}
    assert plan.shared == ["shop/util/money.py"] and "shop/payment/gateway.py" in plan.files


def test_a_name_that_is_not_a_function_blocks_the_extraction(tmp_path: Path) -> None:
    files = {**SHOP, "shop/order/checkout.py": "from shop.payment.service import RATE\n\nx = RATE\n"}
    files["shop/payment/service.py"] = "RATE = 3\n"
    plan = ex.plan_extraction(project(tmp_path, files), RULES, "payment")
    assert "`RATE`" in plan.blocked and "not a function" in plan.blocked


def test_a_dependency_on_a_group_not_yet_extracted_blocks_it(tmp_path: Path) -> None:
    files = {
        **SHOP,
        "shop/payment/gateway.py": "from shop.order.checkout import place\n\n\ndef fee(a):\n    return a\n",
    }
    plan = ex.plan_extraction(project(tmp_path, files), RULES, "payment")
    assert "order group, which has not been extracted" in plan.blocked


def test_the_shim_serves_the_local_code_by_default_and_the_service_by_share(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    plan = ex.plan_extraction(work, RULES, "payment", frozenset({"util"}))
    ex.apply_extraction(work, plan, b.py_roots(work), "payment_service")
    shim = (work / "shop/payment/service.py").read_text(encoding="utf-8")
    assert shim.startswith(ex.SHIM_MARK) and "async def refund" in shim and "_local_service" in shim
    assert (work / "shop/payment/_local_service.py").read_text(encoding="utf-8") == SHOP["shop/payment/service.py"]
    assert (work / "services/payment/src/shop/payment/gateway.py").is_file()
    assert (work / "services/payment/src/shop/util/money.py").is_file()
    for rel in ("shop/payment/service.py", "services/payment/src/payment_service/codewright_rpc.py"):
        py_compile.compile(str(work / rel), doraise=True)
    # 0%: the local code answers, nothing is called
    done = run("from shop.order.checkout import place; print(place(10))", work)
    assert done.returncode == 0 and "'charged': 20" in done.stdout, done.stderr
    # 100% with nothing listening: the call fails (no fallback at 100%)
    down = run(
        "from shop.order.checkout import place; place(10)",
        work,
        CUTOVER_PERCENT_PAYMENT="100",
        SERVICE_URL_PAYMENT="http://127.0.0.1:9",
    )
    assert down.returncode != 0 and "TransportError" in down.stderr
    # 50% with nothing listening: falls back to the local code
    half = run(
        "from shop.order.checkout import place; print(place(10)['charged'])",
        work,
        CUTOVER_PERCENT_PAYMENT="50",
        SERVICE_URL_PAYMENT="http://127.0.0.1:9",
    )
    assert half.returncode == 0 and half.stdout.strip() == "20", half.stderr
    # loopback: the arguments and the result go through JSON
    loop = run(
        "from shop.order.checkout import place; print(place(10)['currency'])", work, CODEWRIGHT_ACL_MODE="loopback"
    )
    assert loop.returncode == 0 and loop.stdout.strip() == "USD"


SERVER = """
import importlib, json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "src")
EXPOSED = {"shop.payment.service": ["charge"]}

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        _, _, module, function = self.path.split("/", 3)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if function not in EXPOSED.get(module, []):
            return self.send(404, {"detail": "not exposed"})
        try:
            result = getattr(importlib.import_module(module), function)(*body["args"], **body["kwargs"])
        except Exception as exc:
            return self.send(500, {"error": {"type": type(exc).__name__, "message": str(exc)}})
        self.send(200, {"result": result})
    def send(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def log_message(self, *a): pass

server = HTTPServer(("127.0.0.1", 0), H)
print(server.server_port, flush=True)
server.handle_request(); server.handle_request()
"""


def test_a_call_really_reaches_the_extracted_copy_over_http(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    plan = ex.plan_extraction(work, RULES, "payment", frozenset({"util"}))
    ex.apply_extraction(work, plan, b.py_roots(work), "payment_service")
    import os  # noqa: PLC0415

    # The service side runs its own copy of the code, from its own folder, with the monolith out of its path.
    server = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", SERVER],
        cwd=work / "services/payment",
        stdout=subprocess.PIPE,
        text=True,
        env={"PATH": os.environ.get("PATH", "")},
    )
    try:
        assert server.stdout is not None
        port = server.stdout.readline().strip()
        done = run(
            "from shop.order.checkout import place; print(place(10))",
            work,
            CUTOVER_PERCENT_PAYMENT="100",
            SERVICE_URL_PAYMENT=f"http://127.0.0.1:{port}",
        )
        assert done.returncode == 0, done.stderr
        assert "'currency': 'USD'" in done.stdout and "'charged': 20" in done.stdout
        # a function that raises in the service comes back as a ServiceError
        bad = run(
            "from shop.payment.service import charge; charge()",
            work,
            CUTOVER_PERCENT_PAYMENT="100",
            SERVICE_URL_PAYMENT=f"http://127.0.0.1:{port}",
        )
        assert bad.returncode != 0 and "ServiceError" in bad.stderr and "TypeError" in bad.stderr
    finally:
        server.kill()


def test_removing_the_local_code_leaves_clients_and_is_exactly_undoable(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    plan = ex.plan_extraction(work, RULES, "payment", frozenset({"util"}))
    ex.apply_extraction(work, plan, b.py_roots(work), "payment_service")
    before = ex.remove_local(work, plan, b.py_roots(work))
    assert not (work / "shop/payment/_local_service.py").exists() and not (work / "shop/payment/gateway.py").exists()
    client = (work / "shop/payment/service.py").read_text(encoding="utf-8")
    assert "_local" not in client and "remote(" in client and "async def refund" in client
    ex.restore(work, before)
    assert (work / "shop/payment/_local_service.py").is_file() and (work / "shop/payment/gateway.py").is_file()
    assert "_local" in (work / "shop/payment/service.py").read_text(encoding="utf-8")


def test_applying_an_extraction_is_exactly_undoable(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    plan = ex.plan_extraction(work, RULES, "payment", frozenset({"util"}))
    before = ex.apply_extraction(work, plan, b.py_roots(work), "payment_service")
    ex.restore(work, before)
    assert (work / "shop/payment/service.py").read_text(encoding="utf-8") == SHOP["shop/payment/service.py"]
    assert not (work / "shop/payment/_local_service.py").exists() and not (work / "codewright_acl.py").exists()
    assert not (work / "services/payment/src/shop/payment/gateway.py").exists()
