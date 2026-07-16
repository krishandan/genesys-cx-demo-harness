"""Verification-factor hashing.

Deterministic on purpose: the seed and a later verify-customer call must derive the
same digest for the same factor, and no plaintext factor is ever persisted. The data
is synthetic demo data, never real PII, so a salted KDF would buy nothing here beyond
breaking the deterministic re-seed the phase gate depends on.
"""

import hashlib


def hash_factor(factor_type: str, value: str) -> str:
    """Digest a verification factor. Namespaced by factor_type so a zip and a pin
    with the same digits do not collide."""
    normalized = value.strip().lower()
    return hashlib.sha256(f"{factor_type}:{normalized}".encode()).hexdigest()
