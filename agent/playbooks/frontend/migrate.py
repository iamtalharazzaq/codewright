"""React (Vite) → Next.js (App Router), as file operations computed from the project's own files.

The move keeps the app's behavior: the existing `App` runs as a client component under one catch-all route, so every
URL (including client-side routes) still works, and nothing is rewritten by a model. Pages can then be moved to
server components one at a time. Environment variables, the dev-server proxy and the test setup are carried over.
Unsupported shapes (no Vite, no entry file, Create React App) are reported, not guessed.
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path

from agent.language_packs.base import Component, walk

NEXT_VERSION = "^15.0.0"
ENTRY_NAMES = ("main.tsx", "main.jsx", "main.ts", "main.js", "index.tsx", "index.jsx")
CONFIG_NAMES = ("vite.config.ts", "vite.config.js", "vite.config.mjs", "vite.config.mts")
ENV_MAP = (
    (re.compile(r"import\.meta\.env\.VITE_(\w+)"), r"process.env.NEXT_PUBLIC_\1"),
    (re.compile(r"import\.meta\.env\.MODE\b"), "process.env.NODE_ENV"),
    (re.compile(r"import\.meta\.env\.DEV\b"), "(process.env.NODE_ENV !== 'production')"),
    (re.compile(r"import\.meta\.env\.PROD\b"), "(process.env.NODE_ENV === 'production')"),
    (re.compile(r"import\.meta\.env\.BASE_URL\b"), "''"),
)
PROXY = re.compile(r"""['"](/[\w/-]*)['"]\s*:\s*(?:\{[^}]*?target\s*:\s*)?['"](https?://[^'"]+)['"]""", re.S)
CSS_IMPORT = re.compile(r"""^import\s+['"](\.{1,2}/[^'"]+\.css)['"];?\s*$""", re.M)


@dataclass
class Operation:
    path: str  # relative to the project root
    content: str | None  # None: delete
    why: str


@dataclass
class Migration:
    operations: list[Operation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    supported: bool = True


def can_migrate(c: Component) -> bool:
    return c.pack in {"typescript", "javascript"} and "react" in c.frameworks and "vite" in c.frameworks


def _join(c: Component, name: str) -> str:
    return name if c.path == "." else f"{c.path}/{name}"


def _rel_import(from_dir: str, target: str) -> str:
    """A module specifier from the folder `from_dir` to `target` (both relative to the same root), no extension."""
    path = posixpath.relpath(re.sub(r"\.(?:tsx|jsx|ts|js)$", "", target), from_dir)
    return path if path.startswith(".") else "./" + path


def migration(work: Path, c: Component) -> Migration:  # noqa: PLR0912, PLR0915
    out = Migration()
    root = work / c.path
    ts = c.pack == "typescript"
    ext = "tsx" if ts else "jsx"
    if not can_migrate(c):
        return Migration(
            notes=[f"`{c.path}` is not a React + Vite app, so there is nothing to move to Next.js"], supported=False
        )
    entry = next((f"src/{n}" for n in ENTRY_NAMES if (root / "src" / n).is_file()), None)
    app = next((f"src/App.{e}" for e in ("tsx", "jsx", "js", "ts") if (root / f"src/App.{e}").is_file()), None)
    if not entry or not app:
        return Migration(
            notes=["No `src/main` entry and `src/App` were found, so the app's shape is unclear"], supported=False
        )
    src_dir = (root / "src").is_dir()
    app_dir = "src/app" if src_dir else "app"
    if (root / app_dir).exists() or (root / "pages").exists():
        return Migration(
            notes=[f"`{app_dir}` or `pages` already exists, so this is not a plain Vite app"], supported=False
        )

    # package.json
    pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
    config_name = next((n for n in CONFIG_NAMES if (root / n).is_file()), None)
    config = (root / config_name).read_text(encoding="utf-8") if config_name else ""
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    keeps_vite = bool(re.search(r"\btest\s*:", config)) or "vitest" in deps  # the tests run on Vite's config
    scripts = pkg.setdefault("scripts", {})
    scripts.update({"dev": "next dev", "build": "next build", "start": "next start"})
    scripts.pop("preview", None)
    pkg.setdefault("dependencies", {})["next"] = NEXT_VERSION
    if not keeps_vite:
        for group in ("dependencies", "devDependencies"):
            for name in [n for n in pkg.get(group, {}) if n == "vite" or n.startswith("@vitejs/")]:
                del pkg[group][name]
    if ts and "build" in scripts and scripts["build"].startswith("tsc"):
        scripts["build"] = "next build"
    out.operations.append(
        Operation(_join(c, "package.json"), json.dumps(pkg, indent=2) + "\n", "Next.js scripts and dependency")
    )

    # config files
    if config_name:
        if keeps_vite:
            new_name = config_name.replace("vite.config", "vitest.config")
            out.operations += [
                Operation(_join(c, new_name), config, "the tests keep their Vite-based setup"),
                Operation(_join(c, config_name), None, "replaced by next.config.mjs"),
            ]
        else:
            out.operations.append(Operation(_join(c, config_name), None, "replaced by next.config.mjs"))
    rewrites = [(s, t) for s, t in PROXY.findall(config) if s != "/"]
    if rewrites:
        items = ",\n".join(
            f"      {{ source: '{s}/:path*', destination: '{t.rstrip('/')}{s}/:path*' }}" for s, t in rewrites
        )
        body = f"  async rewrites() {{\n    return [\n{items},\n    ]\n  }},\n"
        out.notes.append(
            "The dev-server proxy " + ", ".join(f"`{s}` → {t}" for s, t in rewrites) + " became Next.js rewrites."
        )
    else:
        body = ""
    out.operations.append(
        Operation(
            _join(c, "next.config.mjs"),
            f"/** @type {{import('next').NextConfig}} */\nexport default {{\n  reactStrictMode: true,\n{body}}}\n",
            "Next.js configuration",
        )
    )

    # tsconfig
    if ts and (root / "tsconfig.json").is_file():
        try:
            ts_conf = json.loads((root / "tsconfig.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            ts_conf = None
            out.notes.append(
                "`tsconfig.json` has comments, so it was not edited: set `jsx` to `preserve` and add the `next` plugin yourself."  # noqa: E501
            )
        if ts_conf is not None and "references" not in ts_conf:
            opts = ts_conf.setdefault("compilerOptions", {})
            opts.update({"jsx": "preserve", "incremental": True, "noEmit": True, "plugins": [{"name": "next"}]})
            ts_conf["include"] = sorted({*ts_conf.get("include", ["src"]), "next-env.d.ts", ".next/types/**/*.ts"})
            out.operations.append(
                Operation(
                    _join(c, "tsconfig.json"), json.dumps(ts_conf, indent=2) + "\n", "Next.js TypeScript settings"
                )
            )
        elif ts_conf is not None:
            out.notes.append(
                "`tsconfig.json` uses project references, so it was left as it is; Next.js may add its own settings."
            )

    # the shell: layout + one catch-all page that renders App on the client
    main_text = (root / entry).read_text(encoding="utf-8")
    css = [m for m in CSS_IMPORT.findall(main_text)]
    css_specs = [
        _rel_import(app_dir, posixpath.normpath(posixpath.join(posixpath.dirname(entry), spec))) for spec in css
    ]
    index = (root / "index.html").read_text(encoding="utf-8") if (root / "index.html").is_file() else ""
    found_title = re.search(r"<title>(.*?)</title>", index, re.S)
    title = found_title.group(1).strip() if found_title else "App"
    desc = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', index)
    meta = f"  title: {json.dumps(title)},\n" + (f"  description: {json.dumps(desc.group(1))},\n" if desc else "")
    types = "import type { Metadata } from 'next'\nimport type { ReactNode } from 'react'\n" if ts else ""
    imports = "".join(f"import '{s}'\n" for s in css_specs)
    layout = (
        f"{types}{imports}\nexport const metadata{': Metadata' if ts else ''} = {{\n{meta}}}\n\n"
        f"export default function RootLayout({{ children }}{': { children: ReactNode }' if ts else ''}) {{\n"
        '  return (\n    <html lang="en">\n      <body>{children}</body>\n    </html>\n  )\n}\n'
    )
    app_import = _rel_import(app_dir + "/[[...slug]]", app)
    client = (
        f"'use client'\n\nimport dynamic from 'next/dynamic'\n\n// The existing App runs in the browser, as before, so every route and browser-only API keeps working.\n"  # noqa: E501
        f"const App = dynamic(() => import('{app_import}'), {{ ssr: false }})\n\nexport default function Client() {{\n  return <App />\n}}\n"  # noqa: E501
    )
    page = "import Client from './client'\n\nexport default function Page() {\n  return <Client />\n}\n"
    if ts:
        page = "import Client from './client'\n\nexport function generateStaticParams() {\n  return [{ slug: [] }]\n}\n\nexport default function Page() {\n  return <Client />\n}\n"  # noqa: E501
    out.operations += [
        Operation(_join(c, f"{app_dir}/layout.{ext}"), layout, "root layout: title, description, global styles"),
        Operation(_join(c, f"{app_dir}/[[...slug]]/client.{ext}"), client, "runs the existing App in the browser"),
        Operation(_join(c, f"{app_dir}/[[...slug]]/page.{ext}"), page, "one route for every URL the app handled"),
        Operation(_join(c, entry), None, "Next.js is the entry now"),
    ]
    if index:
        out.operations.append(Operation(_join(c, "index.html"), None, "title and description moved to the layout"))

    # code: env variables
    changed = 0
    for f in walk(root / "src", (".ts", ".tsx", ".js", ".jsx"), limit=3000):
        rel = f.relative_to(work).as_posix()
        if rel == _join(c, entry):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        new = text
        for rx, repl in ENV_MAP:
            new = rx.sub(repl, new)
        if new != text:
            out.operations.append(Operation(rel, new, "Vite env variables → process.env"))
            changed += 1
    for envfile in root.glob(".env*"):
        text = envfile.read_text(encoding="utf-8", errors="ignore")
        new = re.sub(r"(?m)^VITE_", "NEXT_PUBLIC_", text)
        if new != text:
            out.operations.append(Operation(envfile.relative_to(work).as_posix(), new, "VITE_ → NEXT_PUBLIC_"))
    gi = root / ".gitignore"
    if gi.is_file() and ".next" not in gi.read_text(encoding="utf-8"):
        out.operations.append(
            Operation(
                _join(c, ".gitignore"),
                gi.read_text(encoding="utf-8").rstrip("\n") + "\n.next\nnext-env.d.ts\n",
                "ignore Next.js build output",
            )
        )
    if changed:
        out.notes.append(f"{changed} source file(s) used `import.meta.env`; they now read `process.env`.")
    if keeps_vite:
        out.notes.append("Vite stays as a dev dependency only for the tests (its config became `vitest.config`).")
    return out
