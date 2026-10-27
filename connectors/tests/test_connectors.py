from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from connectors.inputs import InputError, ZipLimits, copy_local, drive_file_id, extract_zip, parse_github
from connectors.outputs import DeliveryError, make_zip, to_local


def _zip(path: Path, files: dict[str, bytes | str]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


def test_extract_unwraps_a_single_top_folder(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "a.zip", {"goshop-main/main.go": "package main", "goshop-main/go.mod": "module x"})
    root = extract_zip(archive, tmp_path / "out")
    assert sorted(p.name for p in root.iterdir()) == ["go.mod", "main.go"]


@pytest.mark.parametrize("name", ["../evil.txt", "/etc/passwd", "a/../../evil.txt"])
def test_unsafe_paths_are_rejected(tmp_path: Path, name: str) -> None:
    archive = _zip(tmp_path / "evil.zip", {name: "x"})
    with pytest.raises(InputError, match="unsafe path"):
        extract_zip(archive, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_symlinks_are_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "link.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = 0o120777 << 16  # a symlink
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(InputError):
        extract_zip(archive, tmp_path / "out")


def test_zip_bombs_are_rejected(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "bomb.zip", {"zeros.txt": b"\0" * 5_000_000})
    with pytest.raises(InputError):
        extract_zip(archive, tmp_path / "out")
    with pytest.raises(InputError):
        extract_zip(_zip(tmp_path / "big.zip", {"a.txt": "x" * 2000}), tmp_path / "o2", ZipLimits(max_file_bytes=1000))


def test_not_a_zip(tmp_path: Path) -> None:
    (tmp_path / "x.zip").write_text("hello")
    with pytest.raises(InputError):
        extract_zip(tmp_path / "x.zip", tmp_path / "out")


def test_parse_github_and_drive_links() -> None:
    assert parse_github("https://github.com/quangdangfit/goshop") == ("quangdangfit", "goshop")
    assert parse_github("https://github.com/quangdangfit/goshop.git") == ("quangdangfit", "goshop")
    with pytest.raises(InputError):
        parse_github("https://gitlab.com/a/b")
    assert (
        drive_file_id("https://drive.google.com/file/d/1AbC_xyz-1234567890abcdefGHIJ/view?usp=sharing")
        == "1AbC_xyz-1234567890abcdefGHIJ"
    )
    with pytest.raises(InputError):
        drive_file_id("https://example.com/file")


def test_copy_local_stays_inside_the_shared_folder(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    (shared / "goshop").mkdir(parents=True)
    (shared / "goshop" / "main.go").write_text("package main")
    out = copy_local("goshop", shared, tmp_path / "copy")
    assert (out / "main.go").is_file()
    for bad in ("../", "/etc", "goshop/../../"):
        with pytest.raises(InputError):
            copy_local(bad, shared, tmp_path / f"c{len(bad)}")
    with pytest.raises(InputError):
        copy_local("goshop", None, tmp_path / "none")


def test_deliver_zip_and_local(tmp_path: Path) -> None:
    src = tmp_path / "work"
    (src / ".git").mkdir(parents=True)
    (src / ".git" / "HEAD").write_text("ref")
    (src / "main.go").write_text("package main")
    archive = make_zip(src, tmp_path / "out" / "p.zip")
    with zipfile.ZipFile(archive) as zf:
        assert zf.namelist() == ["main.go"]

    outputs = tmp_path / "deliveries"
    outputs.mkdir()
    copied = to_local(src, [outputs], "goshop")
    assert copied.parent == outputs and (copied / "main.go").is_file()
    with pytest.raises(DeliveryError):
        to_local(src, [], "goshop")
