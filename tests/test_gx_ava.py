"""AVA tool-schema compliance.

AVA rejects a non-compliant tool *silently* — it vanishes on save with no error — so
there is no feedback loop in Genesys to catch this. These tests are the feedback loop:
they assert the rules across every committed contract, so a future endpoint cannot
quietly break the agent.
"""

import json

import pytest

from app.gx.ava import (
    FORBIDDEN_KEYWORDS,
    AvaComplianceError,
    validate_ava_schema,
    validate_contract,
)
from app.gx.contracts import ACTIONS, CONTRACTS_DIR, build_all

SLUGS = [a.slug for a in ACTIONS]


def _committed(slug: str) -> dict:
    return json.loads((CONTRACTS_DIR / f"{slug}.json").read_text())


def _all_property_names(schema: dict) -> list[str]:
    """Every property name in an output schema, object or top-level-array feed."""
    node = schema["items"] if schema.get("type") == "array" else schema
    return list(node.get("properties", {}))


# ── the rules, across every real contract ────────────────────────────────────────────


@pytest.mark.parametrize("slug", SLUGS)
def test_every_committed_contract_is_ava_compliant(slug: str) -> None:
    validate_contract(_committed(slug), slug)


@pytest.mark.parametrize("slug", SLUGS)
def test_no_dots_in_any_property_name(slug: str) -> None:
    """The confirmed real-world cause of a tool vanishing on save."""
    definition = _committed(slug)
    names = _all_property_names(definition["contract"]["output"]["successSchema"])
    names += list(definition["contract"]["input"]["inputSchema"]["properties"])

    assert names
    for name in names:
        assert "." not in name, f"{slug}: property '{name}' contains a dot"


@pytest.mark.parametrize("slug", SLUGS)
def test_no_forbidden_keywords_anywhere_in_a_contract(slug: str) -> None:
    """Belt and braces: scan the raw JSON text of the contract block, so a keyword
    nested anywhere is caught even if the walker missed a shape."""
    contract_text = json.dumps(_committed(slug)["contract"])

    for keyword in FORBIDDEN_KEYWORDS:
        assert f'"{keyword}"' not in contract_text, f"{slug} uses {keyword}"


@pytest.mark.parametrize("slug", SLUGS)
def test_every_output_property_has_an_agent_facing_description(slug: str) -> None:
    schema = _committed(slug)["contract"]["output"]["successSchema"]
    node = schema["items"] if schema.get("type") == "array" else schema

    for name, spec in node["properties"].items():
        assert spec.get("description", "").strip(), f"{slug}.{name} has no description"


@pytest.mark.parametrize("slug", SLUGS)
def test_no_nested_arrays_in_outputs(slug: str) -> None:
    schema = _committed(slug)["contract"]["output"]["successSchema"]
    node = schema["items"] if schema.get("type") == "array" else schema

    for name, spec in node["properties"].items():
        assert spec["type"] != "array", f"{slug}.{name} is a nested array"


# ── the generator enforces it, not just the test ─────────────────────────────────────


def test_generation_is_where_compliance_is_enforced() -> None:
    """build_all runs the validator, so a non-compliant endpoint cannot be exported."""
    for slug, definition in build_all().items():
        validate_contract(definition, slug)


# ── each rule actually rejects ───────────────────────────────────────────────────────


def _obj(**properties: dict) -> dict:
    return {"type": "object", "properties": properties}


def test_a_dot_in_a_property_name_is_rejected() -> None:
    schema = _obj(**{"device.label": {"type": "string", "description": "d"}})

    with pytest.raises(AvaComplianceError, match="dot"):
        validate_ava_schema(schema, "test")


@pytest.mark.parametrize("keyword", FORBIDDEN_KEYWORDS)
def test_each_forbidden_keyword_is_rejected(keyword: str) -> None:
    schema = _obj(ok={"type": "string", "description": "d"})
    schema[keyword] = ["anything"]

    with pytest.raises(AvaComplianceError, match=keyword.replace("$", r"\$")):
        validate_ava_schema(schema, "test")


def test_a_nested_array_property_is_rejected() -> None:
    schema = _obj(devices={"type": "array", "description": "d", "items": {"type": "string"}})

    with pytest.raises(AvaComplianceError, match="array"):
        validate_ava_schema(schema, "test")


def test_an_array_of_arrays_is_rejected() -> None:
    schema = {"type": "array", "items": {"type": "array"}}

    with pytest.raises(AvaComplianceError, match="array"):
        validate_ava_schema(schema, "test")


def test_tuple_validation_is_rejected() -> None:
    schema = {"type": "array", "items": [{"type": "string"}, {"type": "integer"}]}

    with pytest.raises(AvaComplianceError, match="tuple"):
        validate_ava_schema(schema, "test")


def test_an_empty_object_is_rejected() -> None:
    with pytest.raises(AvaComplianceError, match="no properties"):
        validate_ava_schema({"type": "object", "properties": {}}, "test")


def test_a_missing_description_is_rejected() -> None:
    schema = _obj(ok={"type": "string"})

    with pytest.raises(AvaComplianceError, match="description"):
        validate_ava_schema(schema, "test")


def test_a_property_name_starting_with_a_digit_is_rejected() -> None:
    schema = _obj(**{"2fa_enabled": {"type": "string", "description": "d"}})

    with pytest.raises(AvaComplianceError, match="AVA-safe"):
        validate_ava_schema(schema, "test")


def test_a_top_level_array_of_flat_objects_is_allowed() -> None:
    """The one array shape AVA accepts — how /gx/devices and the feeds are shaped."""
    schema = {
        "type": "array",
        "items": _obj(label={"type": "string", "description": "Device name."}),
    }

    validate_ava_schema(schema, "test")  # must not raise


def test_a_compliant_object_is_allowed() -> None:
    validate_ava_schema(
        _obj(
            found={"type": "boolean", "description": "Whether it resolved."},
            device_label={"type": "string", "description": "Human device name."},
        ),
        "test",
    )
