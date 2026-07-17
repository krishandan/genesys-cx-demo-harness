import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.gx.contracts import (
    ACTIONS,
    CONTRACTS_DIR,
    GxAction,
    InputField,
    NestedContractError,
    build_all,
    export,
)

SCALARS = {"string", "boolean", "integer", "number"}


def test_one_contract_file_per_gx_endpoint() -> None:
    for action in ACTIONS:
        assert (CONTRACTS_DIR / f"{action.slug}.json").exists(), action.slug


def test_committed_contracts_match_the_endpoints(tmp_path: Path) -> None:
    """Drift guard: a contract must never describe an endpoint that has moved on."""
    export(tmp_path)

    for action in ACTIONS:
        committed = json.loads((CONTRACTS_DIR / f"{action.slug}.json").read_text())
        regenerated = json.loads((tmp_path / f"{action.slug}.json").read_text())
        assert committed == regenerated, (
            f"contracts/{action.slug}.json is stale — run `make contracts`"
        )


def _output_properties(schema: dict) -> dict:
    """The scalar properties, whether the output is an object or a top-level array of
    flat objects (a feed). A nested array inside a property is still forbidden."""
    if schema["type"] == "array":
        return schema["items"]["properties"]
    return schema["properties"]


@pytest.mark.parametrize("slug", [a.slug for a in ACTIONS])
def test_contract_output_is_flat(slug: str) -> None:
    definition = build_all()[slug]
    schema = definition["contract"]["output"]["successSchema"]
    properties = _output_properties(schema)

    assert properties
    for name, spec in properties.items():
        assert spec["type"] in SCALARS, f"{slug}.{name} is not a scalar: {spec}"


def test_only_the_declared_feed_endpoints_are_arrays() -> None:
    array_slugs = {
        a.slug
        for a in ACTIONS
        if build_all()[a.slug]["contract"]["output"]["successSchema"]["type"] == "array"
    }

    assert array_slugs == {"telemetry"}


@pytest.mark.parametrize("slug", [a.slug for a in ACTIONS])
def test_contract_input_is_flat(slug: str) -> None:
    definition = build_all()[slug]
    properties = definition["contract"]["input"]["inputSchema"]["properties"]

    for name, spec in properties.items():
        assert spec["type"] in SCALARS, f"{slug}.{name} is not a scalar: {spec}"


@pytest.mark.parametrize("slug", [a.slug for a in ACTIONS])
def test_contract_is_importable_shape(slug: str) -> None:
    definition = build_all()[slug]

    assert definition["name"]
    assert definition["integrationType"] == "custom-rest-actions"
    request = definition["config"]["request"]
    assert request["requestUrlTemplate"].startswith("https://")
    assert request["requestType"] in {"GET", "POST"}
    # The key comes from the integration's credential, never from a flow.
    assert request["headers"]["X-API-Key"] == "${credentials.apiKey}"
    assert definition["config"]["response"]["successTemplate"] == "${rawResult}"


def test_base_url_is_config_not_a_literal() -> None:
    definition = build_all(base_url="https://example.invalid")["customer-context"]

    assert definition["config"]["request"]["requestUrlTemplate"].startswith(
        "https://example.invalid/"
    )


def test_generation_refuses_a_nested_output() -> None:
    """The flatness rule is structural: a nested model cannot be exported at all."""

    class Nested(BaseModel):
        found: bool
        identities: list[str]  # exactly what Genesys cannot express

    bad = GxAction(
        slug="bad",
        name="Bad",
        method="GET",
        path="/gx/bad",
        output_model=Nested,
        inputs=[InputField(name="x", type="string", description="x")],
    )

    with pytest.raises(NestedContractError, match="nested arrays"):
        from app.gx.contracts import build_action

        build_action(bad, "https://example.invalid")


def test_contracts_are_valid_json_on_disk() -> None:
    for action in ACTIONS:
        payload: dict[str, Any] = json.loads((CONTRACTS_DIR / f"{action.slug}.json").read_text())
        assert payload["contract"]["input"]["inputSchema"]["type"] == "object"
        assert payload["contract"]["output"]["successSchema"]["type"] in {"object", "array"}
