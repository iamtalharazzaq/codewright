import pytest

from {{name_snake}} import slugify, truncate


def test_slugify() -> None:
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("  --  ") == ""


def test_truncate() -> None:
    assert truncate("short", 10) == "short"
    assert truncate("a longer sentence", 8) == "a longe…"


def test_truncate_rejects_a_tiny_limit() -> None:
    with pytest.raises(ValueError):
        truncate("anything", 0)
