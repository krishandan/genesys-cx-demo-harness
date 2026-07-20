"""Masking for gx responses. Shape comes from tenant config, not from code."""

from typing import Any

DEFAULT_MASKED_NAME: dict[str, Any] = {
    "reveal_chars": 1,
    "mask_char": "*",
    "mask_length": 3,
}

DEFAULT_MASKED_EMAIL: dict[str, Any] = {
    "reveal_chars": 1,
    "mask_char": "•",
    "mask_length": 4,
}


def mask_name(display_name: str, config: dict[str, Any] | None = None) -> str:
    """Mask a display name so a flow can confirm who verified without disclosing them.

    'Anne Clark-Phillips' -> 'A*** C***'

    mask_length is a fixed run rather than the token's real length, so the response
    does not leak how long the name is.
    """
    cfg = {**DEFAULT_MASKED_NAME, **(config or {})}
    reveal = max(0, int(cfg["reveal_chars"]))
    mask_char = str(cfg["mask_char"])
    mask_length = max(0, int(cfg["mask_length"]))

    tokens = display_name.split()
    if not tokens:
        return ""

    return " ".join(token[:reveal] + mask_char * mask_length for token in tokens)


def mask_email(email: str, config: dict[str, Any] | None = None) -> str:
    """Mask an address so the agent can confirm where something went without reciting it.

    'anne.clark-phillips.0@example.net' -> 'a••••@example.net'

    The domain is kept: it is the part that makes the confirmation meaningful ("the
    address ending example.net"), and it is not the identifying half.
    """
    cfg = {**DEFAULT_MASKED_EMAIL, **(config or {})}
    reveal = max(0, int(cfg["reveal_chars"]))
    mask_char = str(cfg["mask_char"])
    mask_length = max(0, int(cfg["mask_length"]))

    local, at, domain = email.partition("@")
    if not at or not local:
        return ""

    return f"{local[:reveal]}{mask_char * mask_length}{at}{domain}"
