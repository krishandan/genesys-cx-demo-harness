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
from app.gx.ava import validate_contract
from app.gx.schemas import (
    CsatIn,
    CsatOut,
    CustomerContextOut,
    DeviceActionIn,
    DeviceActionOut,
    InteractionEventIn,
    InteractionEventOut,
    NetDiagnosticsOut,
    NetStatusOut,
    TelemetryOut,
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
    # A feed endpoint returns a top-level array of the flat model. Allowed by the gx
    # rule (a top-level array is fine; an array nested in a property is not).
    output_is_array: bool = False


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


def _object_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    properties = {
        name: _scalar_schema(spec, f"{model.__name__}.{name}")
        for name, spec in raw.get("properties", {}).items()
    }
    return {
        "type": "object",
        "properties": properties,
        # Every field is always present and typed, so a flow binds them unconditionally.
        "required": sorted(properties),
        "additionalProperties": True,
    }


def _output_schema(model: type[BaseModel], is_array: bool = False) -> dict[str, Any]:
    """The item schema still passes the scalar-only check, so a feed of flat objects is
    contract-safe while an object holding a nested array is still rejected."""
    inner = _object_schema(model)
    if is_array:
        return {
            "$schema": "http://json-schema.org/draft-04/schema#",
            "title": f"{model.__name__} feed",
            "type": "array",
            "items": inner,
        }
    return {
        "$schema": "http://json-schema.org/draft-04/schema#",
        "title": f"{model.__name__} output",
        **inner,
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
        # esc.url percent-encodes the value. Without it a '+' in an E.164 number
        # decodes to a space server-side and the lookup silently resolves nothing.
        query = "&".join(f"{p}=${{esc.url(input.{p})}}" for p in action.query_params)
        url = f"{url}?{query}"

    # No X-Tenant header: it was bound to an optional input, and an unsupplied optional
    # renders the literal "${input.tenant}" in Velocity, which breaks the lookup. The box
    # is single-tenant, so DEFAULT_TENANT covers it. (BE-6 re-adds it as *required*.)
    headers = {"X-API-Key": "${credentials.apiKey}"}

    request: dict[str, Any] = {
        "requestUrlTemplate": url,
        "requestType": action.method,
        "headers": headers,
    }

    if action.body_fields:
        headers["Content-Type"] = "application/json"
        types = {i.name: i.type for i in action.inputs}
        parts = []
        for f in action.body_fields:
            # Quote strings and run them through esc.jsonString so a quote or backslash
            # in user input cannot break out of the JSON body. Leave integer/number/
            # boolean bare so the body carries the right type (a CSAT score is an int).
            if types.get(f) in {"integer", "number", "boolean"}:
                value = f"${{input.{f}}}"
            else:
                value = f'"${{esc.jsonString(input.{f})}}"'
            parts.append(f'"{f}": {value}')
        request["requestTemplate"] = "{" + ",".join(parts) + "}"

    # A GET has no body, so requestTemplate is spurious there and is left off entirely.
    return request


def build_action(action: GxAction, base_url: str) -> dict[str, Any]:
    definition = {
        "name": action.name,
        "integrationType": "custom-rest-actions",
        # Genesys rejects the import without an explicit actionType.
        "actionType": "custom",
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
            "output": {
                "successSchema": _output_schema(action.output_model, action.output_is_array)
            },
        },
    }

    # Fail generation rather than shipping a contract AVA would silently reject.
    validate_contract(definition, action.slug)
    return definition


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
        inputs=[IDENTIFIER_INPUT],
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
        ],
    ),
    GxAction(
        slug="net-diagnostics",
        name="Backlot - Network Diagnostics",
        method="GET",
        path="/gx/net-diagnostics",
        output_model=NetDiagnosticsOut,
        query_params=["identifier"],
        inputs=[IDENTIFIER_INPUT],
    ),
    GxAction(
        slug="net-status",
        name="Backlot - Network Status",
        method="GET",
        path="/gx/net-status",
        output_model=NetStatusOut,
        query_params=["identifier"],
        inputs=[IDENTIFIER_INPUT],
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
        ],
    ),
    GxAction(
        slug="interaction-event",
        name="Backlot - Record Interaction",
        method="POST",
        path="/gx/interaction-event",
        output_model=InteractionEventOut,
        body_fields=list(InteractionEventIn.model_fields),
        inputs=[
            IDENTIFIER_INPUT,
            InputField(
                name="channel",
                type="string",
                description="webmessaging | voice | sms | email | ...",
            ),
            InputField(
                name="kind", type="string", description="inbound | outbound", required=False
            ),
        ],
    ),
    GxAction(
        slug="csat",
        name="Backlot - Write CSAT",
        method="POST",
        path="/gx/csat",
        output_model=CsatOut,
        body_fields=list(CsatIn.model_fields),
        inputs=[
            IDENTIFIER_INPUT,
            InputField(name="score", type="integer", description="1–5."),
            InputField(name="comment", type="string", description="Free text.", required=False),
            InputField(
                name="conversation_ref",
                type="string",
                description="Genesys conversation id, for correlation.",
                required=False,
            ),
        ],
    ),
    GxAction(
        slug="telemetry",
        name="Backlot - Network Telemetry Feed",
        method="GET",
        path="/gx/telemetry",
        output_model=TelemetryOut,
        output_is_array=True,
        query_params=["identifier"],
        inputs=[IDENTIFIER_INPUT],
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
