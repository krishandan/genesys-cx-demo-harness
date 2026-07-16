"""Flat, contract-safe gx shapes.

Every field is a scalar. No lists, no nested objects, no nulls: Genesys data action
output contracts cannot express nested arrays, and a consistent shape means a flow can
bind every field once and branch on `found` / `verified` rather than handling absent
properties.
"""

from pydantic import BaseModel, Field


class CustomerContextOut(BaseModel):
    found: bool = Field(description="False when the identifier resolves to no subscriber.")
    party_id: str = Field(default="", description="Empty when not found.")
    display_name: str = ""
    tenant_slug: str = ""
    tier: str = ""
    verified: bool = Field(
        default=False,
        description="Always false here; verification is a separate verify-customer call.",
    )
    last_channel: str = ""
    id_type_resolved: str = Field(
        default="",
        description="phone | email | account_no | msisdn | unrecognized",
    )


class VerifyCustomerIn(BaseModel):
    identifier: str
    factor_type: str = Field(description="dob | zip | pin | last4")
    factor_value: str


class VerifyCustomerOut(BaseModel):
    verified: bool
    party_id: str = ""
    masked_name: str = ""
