"""Regression tests for the broker adapter's normalization helpers.

2026-07-07 incident: list_positions() emitted asset_class as
"AssetClass.US_OPTION" (str() of an alpaca-py enum) instead of "us_option".
Every consumer compares against the plain lowercase value, so the exit
sweep's reconcile saw ZERO live option positions and falsely marked the
day-old MARA long_put as vanished. All enum-ish fields must pass through
_status_str at the adapter boundary.
"""

from enum import Enum

from harness.alpaca_glue import _status_str


class FakeAssetClass(str, Enum):
    US_EQUITY = "us_equity"
    US_OPTION = "us_option"


def test_status_str_unwraps_str_enum_to_plain_value():
    assert _status_str(FakeAssetClass.US_OPTION) == "us_option"
    assert _status_str(FakeAssetClass.US_EQUITY) == "us_equity"


def test_status_str_passes_plain_strings_through_lowercased():
    assert _status_str("us_option") == "us_option"
    assert _status_str("FILLED") == "filled"
