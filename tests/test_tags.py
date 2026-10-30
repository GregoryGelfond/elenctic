import pytest

from elenctic.braces import OUTSIDE, Scan, scan
from elenctic.tags import Element, elements


@pytest.mark.parametrize(
    ("text", "state"),
    [
        ("{ { }", Scan(1)),
        ('{ "}', Scan(1, quoted=True)),
        ('{ "a"', Scan(1)),
        (r'"a\\"', Scan(0)),
        (r'"a\\"}', Scan(-1)),
        (r'"a\"', Scan(0, quoted=True)),
        ('"a\\', Scan(0, quoted=True, escaped=True)),
        (r'"a\"}b,c"', Scan(0)),
    ],
)
def test_a_brace_scan_tracks_depth_quotes_and_escapes(text: str, state: Scan) -> None:
    assert scan(text, OUTSIDE) == state


def test_a_payload_that_opens_with_a_brace_is_read_from_its_first_character() -> None:
    assert elements("{a}") == [Element("a", 1, braced=True)]
    assert elements("{a") is None
