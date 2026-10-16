"""normalize_intent keeps the author's letter case (issue #60).

Only whitespace handling and a single trailing period are changed. The first
letter's case must not be altered, because intents are human decisions.
"""

import pytest

from codegraph.annotator import normalize_intent


@pytest.mark.parametrize(
    "typed, stored",
    [
        ("USE THIS", "USE THIS"),
        ("PyPI publishing is manual", "PyPI publishing is manual"),
        ("Fix the parser", "Fix the parser"),
        ("Fix   the parser.", "Fix the parser"),
        ("  PyPI publishing is manual  ", "PyPI publishing is manual"),
        ("ends with two periods..", "ends with two periods."),
        ("", ""),
    ],
)
def test_intent_is_stored_with_case_and_content_kept(typed, stored):
    assert normalize_intent(typed) == stored


def test_only_one_trailing_period_is_removed():
    assert normalize_intent("Done..") == "Done."
