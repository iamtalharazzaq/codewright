"""The Done card offers a web view only for an app that has something to open."""

from codewright_api.chat import _viewable


def test_a_plain_function_has_no_web_view_but_a_browser_app_does() -> None:
    assert _viewable({"choice": {"template": "web-react-js"}}) is True
    assert _viewable({"choice": {"template": "cli-python"}}) is True
    assert _viewable({"choice": {"template": "function-python"}}) is False
    assert _viewable({"choice": {"template": "library-go"}}) is False
    assert _viewable({}) is False
