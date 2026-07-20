"""AVA tool-schema compliance.

Every gx contract is imported into Genesys as a data action, and every data action is a
**tool** the Agentic Virtual Agent can call. AVA validates a tool's schema on save and
**silently rejects** anything non-compliant: the tool simply vanishes, with no error
message. There is no feedback loop, so the only defence is refusing to generate a
non-compliant contract in the first place.

The rules below are the locked set from `01 Decisions log`. The most surprising one is
the dot rule: a `.` anywhere in a property name is a community-confirmed cause of the
silent rejection, which is why it is checked separately from the general name pattern.

A **top-level** array of flat objects is allowed (that is how a feed, and `/gx/devices`,
must be shaped). An array *nested inside a property* is not.
"""

from __future__ import annotations

import re
from typing import Any

# Schema keywords AVA cannot express. Presence of any of these keys sinks the tool.
FORBIDDEN_KEYWORDS = (
    "oneOf",
    "anyOf",
    "allOf",
    "if",
    "then",
    "else",
    "dependencies",
    "$ref",
    "not",
    "const",
)

# Property names: start with a letter, then letters/digits/hyphen/underscore only.
PROPERTY_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

SCALAR_TYPES = frozenset({"string", "boolean", "integer", "number"})


class AvaComplianceError(ValueError):
    """A schema would be silently rejected by AVA. Raised at generation time."""


def _fail(where: str, problem: str, why: str) -> None:
    raise AvaComplianceError(f"{where}: {problem}. {why}")


def _check_property_name(name: str, where: str) -> None:
    if "." in name:
        _fail(
            f"{where}.{name}",
            "property name contains a dot",
            "Dots in output field names are a confirmed cause of AVA silently dropping "
            "the tool on save. Use underscores.",
        )
    if not PROPERTY_NAME_RE.match(name):
        _fail(
            f"{where}.{name}",
            "property name is not AVA-safe",
            "Names must start with a letter and contain only letters, numbers, "
            "hyphens or underscores.",
        )


def _walk(node: Any, where: str, *, is_root: bool) -> None:
    if not isinstance(node, dict):
        return

    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in node:
            _fail(
                where,
                f"uses the '{keyword}' keyword",
                "AVA cannot express it and will drop the tool on save.",
            )

    node_type = node.get("type")

    if node_type == "array":
        if not is_root:
            _fail(
                where,
                "is an array in a nested position",
                "Only a top-level array is allowed; an array inside a property is not.",
            )
        items = node.get("items")
        if isinstance(items, list):
            _fail(
                where,
                "uses tuple validation (a list of item schemas)",
                "AVA needs a single schema for 'items'.",
            )
        if isinstance(items, dict):
            if items.get("type") == "array":
                _fail(
                    f"{where}.items",
                    "is an array of arrays",
                    "'items' may not itself be of type array.",
                )
            _walk(items, f"{where}.items", is_root=False)
        return

    properties = node.get("properties")

    if node_type == "object" or properties is not None:
        if not properties:
            _fail(
                where,
                "is an object with no properties",
                "AVA rejects empty objects; give it typed properties or flatten it away.",
            )
            return

        for name, spec in properties.items():
            _check_property_name(name, where)
            child = f"{where}.{name}"

            if not isinstance(spec, dict):
                _fail(child, "has a non-object schema", "Each property needs a schema object.")
                continue

            if spec.get("type") == "array":
                _fail(
                    child,
                    "is an array nested inside a property",
                    "Flatten it, or expose it as a separate top-level-array endpoint.",
                )

            # The agent reads descriptions to decide when to call a tool and what a
            # field means, so a missing one is a functional defect, not a doc gap.
            if not str(spec.get("description", "")).strip():
                _fail(
                    child,
                    "has no description",
                    "Every property needs an agent-facing description; the agent reasons "
                    "over these.",
                )

            _walk(spec, child, is_root=False)


def validate_ava_schema(schema: dict[str, Any], where: str) -> None:
    """Raise AvaComplianceError if this JSON Schema would be rejected by AVA.

    `where` names the thing being validated, so a failure points at the endpoint.
    """
    _walk(schema, where, is_root=True)


def validate_contract(definition: dict[str, Any], where: str) -> None:
    """Validate both schemas of a generated data-action definition.

    Only the contract's schemas are checked. The action's `config` block legitimately
    contains empty objects (`translationMap`), which are Genesys plumbing rather than
    tool schema.
    """
    contract = definition.get("contract", {})
    validate_ava_schema(
        contract.get("input", {}).get("inputSchema", {}), f"{where} input"
    )
    validate_ava_schema(
        contract.get("output", {}).get("successSchema", {}), f"{where} output"
    )
