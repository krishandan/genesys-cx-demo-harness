"""Identifier normalization at the gx boundary.

Genesys sends whatever the channel gives it: an ANI with a '+', an ANI whose '+' was
eaten by query-string decoding and arrived as a space, a bare national number typed by
a caller, an email, an account number. This turns any of those into a
(value, id_type) pair the spine can resolve by exact match.

Deliberately not in app/core: /v1 stays a faithful low-level view, and fixing this in
/v1 would mask the same failure at the layer Genesys actually binds to. (Locked
decision, 01 Decisions log.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

UNRECOGNIZED: Final = "unrecognized"

# Dial rules per ISO country code. The tenant's country is config; this table maps that
# code to the arithmetic. Adding a country is a row here, not a branch.
COUNTRY_DIAL_RULES: Final[dict[str, dict[str, str]]] = {
    "GB": {"dial_code": "44", "trunk_prefix": "0"},
    "US": {"dial_code": "1", "trunk_prefix": "1"},
    "IE": {"dial_code": "353", "trunk_prefix": "0"},
    "AU": {"dial_code": "61", "trunk_prefix": "0"},
}

# Characters humans and telephony systems sprinkle through numbers.
_PHONE_SEPARATORS: Final = re.compile(r"[\s()\-.]")
_DIGITS_ONLY: Final = re.compile(r"^\d+$")
_EMAIL: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ACCOUNT_NO: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,31}$")

_MIN_E164_DIGITS: Final = 8
_MAX_E164_DIGITS: Final = 15


@dataclass(frozen=True)
class NormalizedIdentifier:
    """The outcome of normalization. `recognized` is False rather than raising, so a
    junk ANI becomes a clean {found: false} for Genesys instead of a 500."""

    value: str
    id_type: str
    recognized: bool

    @classmethod
    def unrecognized(cls, value: str = "") -> NormalizedIdentifier:
        return cls(value=value, id_type=UNRECOGNIZED, recognized=False)


def _restore_eaten_plus(raw: str) -> str:
    """A '+' that was not percent-encoded in a query string decodes to a space, so
    ' 447700900000' is really '+447700900000'. Restore it before anything else."""
    if raw.startswith(" ") and _DIGITS_ONLY.match(raw[1:].strip()):
        return "+" + raw[1:].strip()
    return raw


def _to_e164(digits: str, has_plus: bool, country: str | None) -> str | None:
    """Return an E.164 string, or None if the number cannot be resolved."""
    if has_plus:
        # Already international; trust it if it is a plausible length.
        return f"+{digits}" if _MIN_E164_DIGITS <= len(digits) <= _MAX_E164_DIGITS else None

    rules = COUNTRY_DIAL_RULES.get((country or "").upper())
    if rules is None:
        # No tenant country configured: a bare national number is unresolvable. We do
        # not guess a default country, that would be the hardcode the brief forbids.
        return None

    dial_code = rules["dial_code"]
    trunk_prefix = rules["trunk_prefix"]

    if digits.startswith(dial_code) and len(digits) > len(dial_code) + 4:
        national = digits[len(dial_code) :]
    elif digits.startswith(trunk_prefix):
        national = digits[len(trunk_prefix) :]
    else:
        national = digits

    if not national:
        return None

    candidate = f"+{dial_code}{national}"
    if not (_MIN_E164_DIGITS <= len(candidate) - 1 <= _MAX_E164_DIGITS):
        return None
    return candidate


def normalize_identifier(raw: str | None, country: str | None = None) -> NormalizedIdentifier:
    """Normalize an identifier Genesys sent into (value, id_type).

    `country` is the tenant's ISO country code, used only to resolve bare national
    phone numbers. Email and account_no pass through with their type detected.
    """
    if raw is None:
        return NormalizedIdentifier.unrecognized()

    candidate = _restore_eaten_plus(raw).strip()
    if not candidate:
        return NormalizedIdentifier.unrecognized()

    if "@" in candidate:
        lowered = candidate.lower()
        if _EMAIL.match(lowered):
            return NormalizedIdentifier(value=lowered, id_type="email", recognized=True)
        return NormalizedIdentifier.unrecognized(candidate)

    has_plus = candidate.startswith("+")
    stripped = _PHONE_SEPARATORS.sub("", candidate.removeprefix("+"))

    if _DIGITS_ONLY.match(stripped):
        e164 = _to_e164(stripped, has_plus, country)
        if e164 is not None:
            return NormalizedIdentifier(value=e164, id_type="phone", recognized=True)
        return NormalizedIdentifier.unrecognized(candidate)

    if has_plus:
        # Started like a phone number but is not digits: junk, not an account number.
        return NormalizedIdentifier.unrecognized(candidate)

    if _ACCOUNT_NO.match(candidate):
        return NormalizedIdentifier(value=candidate.upper(), id_type="account_no", recognized=True)

    return NormalizedIdentifier.unrecognized(candidate)
