"""The required BE-1 case table, plus the edges it implies."""

import pytest

from app.gx.normalize import normalize_identifier

GB = "GB"

# (raw, country, expected_value, expected_id_type)
CASES = [
    # The brief's required table.
    ("+447700900000", GB, "+447700900000", "phone"),
    (" 447700900000", GB, "+447700900000", "phone"),  # '+' eaten by query decoding
    ("447700900000", GB, "+447700900000", "phone"),  # E.164 digits, no '+'
    ("07700900000", GB, "+447700900000", "phone"),  # UK national, trunk 0
    ("alice@example.net", GB, "alice@example.net", "email"),
    ("NW000000", GB, "NW000000", "account_no"),
    # Real-world messiness around the same number.
    ("+44 7700 900000", GB, "+447700900000", "phone"),
    ("+44-7700-900000", GB, "+447700900000", "phone"),
    ("(07700) 900000", GB, "+447700900000", "phone"),
    ("  +447700900000  ", GB, "+447700900000", "phone"),
    ("7700900000", GB, "+447700900000", "phone"),  # bare national, no trunk 0
    # Case folding.
    ("Alice@Example.NET", GB, "alice@example.net", "email"),
    ("nw000000", GB, "NW000000", "account_no"),
    # An international number still resolves with no tenant country configured.
    ("+447700900000", None, "+447700900000", "phone"),
    # Another tenant country: the dial rule is table-driven, not GB-specific.
    ("2025550143", "US", "+12025550143", "phone"),
]


@pytest.mark.parametrize(("raw", "country", "value", "id_type"), CASES)
def test_normalization_table(raw: str, country: str | None, value: str, id_type: str) -> None:
    result = normalize_identifier(raw, country)

    assert result.recognized is True
    assert result.value == value
    assert result.id_type == id_type


UNRECOGNIZED = [
    ("", GB),
    ("   ", GB),
    (None, GB),
    ("???", GB),
    ("!!!@@@", GB),
    ("not an identifier", GB),
    ("+notaphone", GB),
    ("@example.net", GB),  # no local part
    ("alice@", GB),  # no domain
    ("+1", GB),  # too short for E.164
    ("+9999999999999999999", GB),  # too long for E.164
    # A bare national number with no tenant country is unresolvable: we do not guess
    # a default country.
    ("07700900000", None),
]


@pytest.mark.parametrize(("raw", "country"), UNRECOGNIZED)
def test_unrecognized_is_clean_not_an_exception(raw: str | None, country: str | None) -> None:
    result = normalize_identifier(raw, country)

    assert result.recognized is False
    assert result.id_type == "unrecognized"


def test_the_space_decoded_plus_matches_the_encoded_form() -> None:
    """The whole point: both spellings must land on the same E.164 value."""
    eaten = normalize_identifier(" 447700900000", GB)
    encoded = normalize_identifier("+447700900000", GB)

    assert eaten.value == encoded.value
    assert eaten.id_type == encoded.id_type


def test_every_spelling_of_one_number_collapses_to_one_value() -> None:
    spellings = [
        "+447700900000",
        " 447700900000",
        "447700900000",
        "07700900000",
        "7700900000",
        "+44 7700 900000",
        "(07700) 900000",
    ]

    values = {normalize_identifier(s, GB).value for s in spellings}

    assert values == {"+447700900000"}
