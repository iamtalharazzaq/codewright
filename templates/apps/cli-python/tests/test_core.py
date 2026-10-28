from {{name_snake}}.cli import main
from {{name_snake}}.core import greet, word_count


def test_greet() -> None:
    assert greet("Ada") == "Hello, Ada!"
    assert greet("  ") == "Hello, world!"


def test_word_count_orders_by_frequency() -> None:
    assert word_count("b a b. C c c") == {"c": 3, "b": 2, "a": 1}


def test_cli_greet(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["greet", "Grace"]) == 0
    assert capsys.readouterr().out == "Hello, Grace!\n"
