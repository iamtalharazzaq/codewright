from __future__ import annotations

from pathlib import Path

from agent.tools.secrets import MASK, mask, scan_text, scan_tree
from agent.tools.workspace import Workspace, git

GH_TOKEN = "ghp_" + "A" * 36


def test_scan_finds_common_secrets() -> None:
    text = "\n".join(
        [
            f"token = '{GH_TOKEN}'",
            "AWS=AKIAABCDEFGHIJKLMNOP",
            "url = postgres://user:hunter2pass@db:5432/x",
            "password = changeme",  # a placeholder, not a secret
            "print('hello')",
        ]
    )
    kinds = {f.line: f.kind for f in scan_text(text, "app.py")}
    assert set(kinds) == {1, 2, 3}
    assert kinds[3] == "password in URL"


def test_mask_keeps_the_code_readable() -> None:
    masked = mask(f'api_key = "s3cr3tvalue123"\nDB=postgres://u:hunter2pass@h/x\nT={GH_TOKEN}')
    assert "s3cr3tvalue123" not in masked
    assert "hunter2pass" not in masked
    assert GH_TOKEN not in masked
    assert 'api_key = "' + MASK in masked
    assert "postgres://u:" + MASK + "@h/x" in masked


def test_scan_tree_flags_env_files_and_skips_vendored(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("X=1\n")
    (tmp_path / ".env.example").write_text("X=\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "a.js").write_text(f"t='{GH_TOKEN}'")
    paths = {f.path for f in scan_tree(tmp_path)}
    assert paths == {".env"}


def test_workspace_import_makes_a_git_repo(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "main.go").write_text("package main\n")
    (tree / "web").mkdir()
    (tree / "web" / "app.ts").write_text("export {}\n")
    ws = Workspace(tmp_path / "workspaces", "p1")
    ws.import_tree(tree)
    assert (ws.source / "main.go").is_file()
    assert ws.current_branch() == "main"
    assert git(ws.work, "log", "--oneline").count("\n") == 0  # one commit

    s = ws.summary()
    assert s.files == 2
    assert s.languages == {"Go": 1, "TypeScript": 1}
    assert s.top_level == ["main.go", "web/"]

    ws.branch("codewright/change")
    (ws.work / "main.go").write_text("package main\n// changed\n")
    assert ws.commit_all("change") is True
    assert ws.commit_all("nothing") is False
    assert (ws.source / "main.go").read_text() == "package main\n"  # the original is never touched
