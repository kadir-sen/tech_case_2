import pytest

from app.domain.money import parse_amount


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3 milyon", 3_000_000.0),
        ("3.5 milyon", 3_500_000.0),
        ("3,5 milyon", 3_500_000.0),
        ("900 bin", 900_000.0),
        ("1 milyon 250 bin", 1_250_000.0),
        ("3800000", 3_800_000.0),
        ("3.800.000", 3_800_000.0),
        ("3.800.000 TL", 3_800_000.0),
        ("3 milyon TL", 3_000_000.0),
        ("4 milyon", 4_000_000.0),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_parse_amount_none_for_empty():
    assert parse_amount(None) is None
    assert parse_amount("") is None
    assert parse_amount("merhaba") is None
