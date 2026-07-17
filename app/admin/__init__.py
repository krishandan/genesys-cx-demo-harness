"""Thin admin UI + scenario control surface.

Admin is a different trust domain from gx. Genesys holds the gx X-API-Key and must
never be able to stage or reset a demo with it; the admin credential must never be
able to read subscriber data through gx. The two are enforced separately and tested
in both directions.
"""
