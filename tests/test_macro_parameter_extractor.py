from typing import Any

import pytest

from octoprint_moonraker_connector.client import extract_macro_parameters


@pytest.mark.parametrize(
    "gcode, expected",
    (
        ("test params.FOO bar", {"FOO": None}),
        ("test params.FOO|default(0) bar", {"FOO": "0"}),
        ('test params.FOO|default("test") bar', {"FOO": "test"}),
        ("test params.FOO|default('test') bar", {"FOO": "test"}),
        ("test params.FOO|default('test\") bar", {"FOO": None}),
        ("test params.FOO|default('the\\'start') bar", {"FOO": "the'start"}),
        ("test params.FOO|default('the\\start') bar", {"FOO": "the\\start"}),
        (
            "test params.FOO|lower bar params.FNORD|default(0)",
            {"FOO": None, "FNORD": "0"},
        ),
    ),
)
def test_extract_macro_parameters(gcode: str, expected: dict[str, Any]):
    actual = extract_macro_parameters(gcode)
    assert actual == expected
