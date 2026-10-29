from miniapp.core import greet, word_count


def test_greet() -> None:
    assert greet("Ada") == "Hello, Ada!"
    assert greet("  ") == "Hello, world!"


def test_word_count_orders_by_frequency() -> None:
    assert word_count("b a b. C c c") == {"c": 3, "b": 2, "a": 1}
