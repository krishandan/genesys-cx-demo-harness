"""Export Genesys Cloud Web Services data-action contracts, one file per gx endpoint.

Run: python -m app.gx.contracts  (or `make contracts`)

Schemas are derived from the live Pydantic gx models rather than hand-written, so a
contract cannot drift from the endpoint it describes. Generation refuses to emit a
non-scalar property, which is what makes "no nested arrays" structural rather than a
thing to remember.

The generated JSON imports into a Genesys **Web Services Data Actions** integration.
The integration's User Defined credential must carry `apiKey`; the actions reference it
as ${credentials.apiKey} so the key never has to travel through a flow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.config import get_settings
from app.gx.schemas import (
    CustomerContextOut,
    DeviceActionIn,
    DeviceActionOut,
    NetDiagnosticsOut,
    NetStatusOut,
    VerifyCustomerIn,
    VerifyCustomerOut,
)

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"

SCALARS = {"string", "boolean", "integer", "number"}


class NestedContractError(ValueError):
    """Raised when a contract would contain something Genesys cannot express."""


@dataclass(frozen=True)
class InputField:
    name: str
    type: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class GxAction:
    """One gx endpoint, and the data action that binds to it."""

    slug: str
    name: str
    method: str
    path: str
    output_model: type[BaseModel]
    inputs: list[InputField]
    query_params: list[str] = field(default_factory=list)
    body_fields: list[str] = field(default_factory=list)


def _scalar_schema(spec: dict[str, Any], where: str) -> dict[str, Any]:
    kind = spec.get("type")
    if kind not in SCALARS:
        raise NestedContractError(
            f"{where} is '{kind}', not a scalar. Genesys data action contracts cannot "
            f"express nested arrays or objects; flatten it at the gx boundary."
        )
    out: dict[str, Any] = {"type": kind}
    if spec.get("description"):
        out["description"] = spec["description"]
    return out


def _output_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    properties = {
        name: _scalar_schema(spec, f"{model.__name__}.{name}")
        for name, spec in raw.get("properties", {}).items()
    }
    return {
        "$schema": "http://json-schema.org/draft-04/schema#",
        "title": f"{model.__name__} output",
        "type": "object",
        "properties": properties,
        # Every field is always present and typed, so a flow binds them unconditionally.
        "required": sorted(properties),
        "additionalProperties": True,
    }


def _input_schema(action: GxAction) -> dict[str, Any]:
    properties = {
        f.name: {"type": f.type, "description": f.description} for f in action.inputs
    }
    required = sorted(f.name for f in action.inputs if f.required)
    return {
        "$schema": "http://json-schema.org/draft-04/schema#",
        "title": f"{action.name} input",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _request_config(action: GxAction, base_url: str) -> dict[str, Any]:
    url = f"{base_url}{action.path}"
    if action.query_params:
        query = "&".join(f"{p}=${{input.{p}}}" for p in action.query_params)
        url = f"{url}?{query}"

    headers = {
        "X-API-Key": "${credentials.apiKey}",
        # Empty resolves to the API's DEFAULT_TENANT, so single-tenant flows can ignore it.
        "X-Tenant": "${input.tenant}",
    }

    request: dict[str, Any] = {
        "requestUrlTemplate": url,
        "requestType": action.method,
        "headers": headers,
        "requestTemplate": "${input.rawRequest}",
    }

    if action.body_fields:
        headers["Content-Type"] = "application/json"
        body = ",".join(f'"{f}": "${{input.{f}}}"' for f in action.body_fields)
        request["requestTemplate"] = "{" + body + "}"

    return request


def build_action(action: GxAction, base_url: str) -> dict[str, Any]:
    return {
        "name": action.name,
        "integrationType": "custom-rest-actions",
        "secure": False,
        "config": {
            "request": _request_config(action, base_url),
            "response": {
                "translationMap": {},
                "translationMapDefaults": {},
                "successTemplate": "${rawResult}",
            },
        },
        "contract": {
            "input": {"inputSchema": _input_schema(action)},
            "output": {"successSchema": _output_schema(action.output_model)},
        },
    }


TENANT_INPUT = InputField(
    name="tenant",
    type="string",
    description="Tenant slug. Leave empty to use the API's default tenant.",
    required=False,
)

IDENTIFIER_INPUT = InputField(
    name="identifier",
    type="string",
    description=(
        "Raw identifier: ANI/phone (E.164 or national), email, or account number. "
        "Normalized server-side, so an unencoded '+' is tolerated."
    ),
)

ACTIONS: list[GxAction] = [
    GxAction(
        slug="customer-context",
        name="Backlot - Get Customer Context",
        method="GET",
        path="/gx/customer-context",
        output_model=CustomerContextOut,
        query_params=["identifier"],
        inputs=[IDENTIFIER_INPUT, TENANT_INPUT],
    ),
    GxAction(
        slug="verify-customer",
        name="Backlot - Verify Customer",
        method="POST",
        path="/gx/verify-customer",
        output_model=VerifyCustomerOut,
        body_fields=list(VerifyCustomerIn.model_fields),
        inputs=[
            InputField(
                name="identifier",
                type="string",
                description="Identifier of the subscriber to verify.",
            ),
            InputField(
                name="factor_type",
                type="string",
                description="Factor to check: dob | zip | pin | last4.",
            ),
            InputField(
                name="factor_value",
                type="string",
                description="The value the caller supplied. Compared as a hash.",
            ),
            TENANT_INPUT,
        ],
    ),
    GxAction(
        slug="net-diagnostics",
        name="Backlot - Network Diagnostics",
        method="GET",
        path="/gx/net-diagnostics",
        output_model=NetDiagnosticsOut,
        query_params=["identifier"],
        inputs=[IDENTIFIER_INPUT, TENANT_INPUT],
    ),
    GxAction(
        slug="net-status",
        name="Backlot - Network Status",
        method="GET",
        path="/gx/net-status",
        output_model=NetStatusOut,
        query_params=["identifier"],
        inputs=[IDENTIFIER_INPUT, TENANT_INPUT],
    ),
    GxAction(
        slug="device-action",
        name="Backlot - Device Action",
        method="POST",
        path="/gx/device-action",
        output_model=DeviceActionOut,
        body_fields=list(DeviceActionIn.model_fields),
        inputs=[
            IDENTIFIER_INPUT,
            InputField(
                name="action",
                type="string",
                description="band-steer | reboot-extender | reboot-ap",
            ),
            InputField(
                name="target",
                type="string",
                description="device_id or ap_id, taken from net-diagnostics primary_target.",
            ),
            InputField(
                name="params",
                type="string",
                description=(
                    "Optional JSON object as a string, e.g. '{\"band\":\"5\"}'. Leave "
                    "empty for the default behaviour."
                ),
                required=False,
            ),
            TENANT_INPUT,
        ],
    ),
]


def build_all(base_url: str | None = None) -> dict[str, dict[str, Any]]:
    """Return {slug: data action definition} for every gx endpoint."""
    url = (base_url or get_settings().gx_base_url).rstrip("/")
    return {action.slug: build_action(action, url) for action in ACTIONS}


def export(target_dir: Path = CONTRACTS_DIR, base_url: str | None = None) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for slug, definition in build_all(base_url).items():
        path = target_dir / f"{slug}.json"
        path.write_text(json.dumps(definition, indent=2) + "\n")
        written.append(path)
    return written


def main() -> int:
    for path in export():
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
