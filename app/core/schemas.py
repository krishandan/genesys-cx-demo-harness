"""Pydantic v2 response models for the internal /v1 surface.

These are the rich internal shapes. The flat, contract-safe /gx wrappers land in BE-1.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: uuid.UUID
    slug: str
    display_name: str
    industry: str
    branding_json: dict[str, Any]
    created_at: datetime


class IdentityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    identity_id: uuid.UUID
    id_type: str
    value: str
    is_primary: bool


class ContactPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel: str
    value: str
    consent: bool


class PartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    party_id: uuid.UUID
    tenant_id: uuid.UUID
    party_type: str
    display_name: str
    tier: str | None
    created_at: datetime
    identities: list[IdentityOut]
    contact_points: list[ContactPointOut]


class HealthOut(BaseModel):
    status: str
    tenant_default: str
    version: str
