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
    """A top-level array is the one array shape AVA accepts, so it stays deliberate:
    the telemetry feed, and the device list the agent matches a named device against."""
    array_slugs = {
        a.slug
        for a in ACTIONS
        if build_all()[a.slug]["contract"]["output"]["successSchema"]["type"] == "array"
    }

    assert array_slugs == {"telemetry", "devices"}


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
    # Genesys rejects the import outright without an explicit actionType.
    assert definition["actionType"] == "custom"
    request = definition["config"]["request"]
    assert request["requestUrlTemplate"].startswith("https://")
    assert request["requestType"] in {"GET", "POST"}
    # The key comes from the integration's credential, never from a flow.
    assert request["headers"]["X-API-Key"] == "${credentials.apiKey}"
    assert definition["config"]["response"]["successTemplate"] == "${rawResult}"


@pytest.mark.parametrize("slug", [a.slug for a in ACTIONS])
def test_no_tenant_input_or_header(slug: str) -> None:
    """An unsupplied optional input renders the literal '${input.tenant}' in Velocity
    and breaks the lookup. Single-tenant box: DEFAULT_TENANT covers it."""
    definition = build_all()[slug]

    assert "tenant" not in definition["contract"]["input"]["inputSchema"]["properties"]
    assert "X-Tenant" not in definition["config"]["request"]["headers"]


@pytest.mark.parametrize("slug", [a.slug for a in ACTIONS])
def test_query_params_are_url_escaped(slug: str) -> None:
    """The documented Velocity form: $esc.url("${input.X}"). A bare $ prefix and a
    quoted full reference; the ${esc.url(input.X)} form is a Velocity parse error at
    import. Escaping also stops a '+' in an E.164 number decoding to a space."""
    action = next(a for a in ACTIONS if a.slug == slug)
    url = build_all()[slug]["config"]["request"]["requestUrlTemplate"]

    for param in action.query_params:
        assert f'{param}=$esc.url("${{input.{param}}}")' in url


@pytest.mark.parametrize("slug", [a.slug for a in ACTIONS])
def test_every_action_has_a_request_template(slug: str) -> None:
    """requestTemplate is required for every request type, GET included: Genesys
    validates it as required and rejects the import without it. A GET has no body, so
    it passes ${input.rawRequest} through unchanged."""
    request = build_all()[slug]["config"]["request"]

    assert request["requestTemplate"]
    if request["requestType"] == "GET":
        assert request["requestTemplate"] == "${input.rawRequest}"


@pytest.mark.parametrize("slug", [a.slug for a in ACTIONS])
def test_post_bodies_escape_string_fields(slug: str) -> None:
    """The documented form $esc.jsonString("${input.X}") stops a quote in user input
    breaking out of the JSON body. String values carry surrounding JSON quotes; numeric
    and boolean values do not, so the body keeps the right type (a CSAT score is an int).
    """
    action = next(a for a in ACTIONS if a.slug == slug)
    definition = build_all()[slug]
    request = definition["config"]["request"]

    if not action.body_fields:
        return

    template = request["requestTemplate"]
    types = {i.name: i.type for i in action.inputs}
    for field_name in action.body_fields:
        escaped = f'$esc.jsonString("${{input.{field_name}}}")'
        if types.get(field_name) in {"integer", "number", "boolean"}:
            assert f'"{field_name}": {escaped}' in template
        else:
            assert f'"{field_name}": "{escaped}"' in template


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


def test_committed_contracts_all_carry_a_request_template() -> None:
    """The regression guard, on disk: the missing requestTemplate is what Genesys
    rejected the import over ('missing the requesttemplate config request definition')."""
    for action in ACTIONS:
        committed = json.loads((CONTRACTS_DIR / f"{action.slug}.json").read_text())
        assert committed["config"]["request"]["requestTemplate"], action.slug


def test_generation_refuses_a_missing_request_template() -> None:
    """A field Genesys validates as required must break the build, not surface at
    import. build_action always emits requestTemplate, so this exercises the assertion
    against a definition doctored to drop it."""
    from app.gx.contracts import MissingRequiredContractField, _assert_genesys_required_fields

    definition = build_all()["customer-context"]
    del definition["config"]["request"]["requestTemplate"]

    with pytest.raises(MissingRequiredContractField, match="requestTemplate"):
        _assert_genesys_required_fields(definition, "customer-context")


@pytest.mark.parametrize("slug", [a.slug for a in ACTIONS])
def test_every_input_reference_is_escaped(slug: str) -> None:
    """Generation must not leave a raw ${input.X} in the URL or body — Genesys treats
    escaping as injection protection. The generator runs this, so a pass here means it
    held for every real contract."""
    from app.gx.contracts import _assert_inputs_are_escaped

    _assert_inputs_are_escaped(build_all()[slug], slug)


def test_generation_refuses_an_unescaped_url_input() -> None:
    """The BE-5 §1 bug, pinned: ${esc.url(input.X)} is not an escaping macro (the ref
    inside is not wrapped as $esc.url("${input.X}")), so it must fail generation."""
    from app.gx.contracts import UnescapedTemplateInput, _assert_inputs_are_escaped

    bad = {
        "config": {
            "request": {
                "requestUrlTemplate": "https://x/y?identifier=${esc.url(input.identifier)}",
                "requestTemplate": "${input.rawRequest}",
            }
        }
    }

    with pytest.raises(UnescapedTemplateInput, match="identifier"):
        _assert_inputs_are_escaped(bad, "bad")


def test_generation_refuses_an_unescaped_body_input() -> None:
    from app.gx.contracts import UnescapedTemplateInput, _assert_inputs_are_escaped

    bad = {
        "config": {
            "request": {
                "requestUrlTemplate": "https://x/y",
                "requestTemplate": '{"comment": "${input.comment}"}',
            }
        }
    }

    with pytest.raises(UnescapedTemplateInput, match="comment"):
        _assert_inputs_are_escaped(bad, "bad")


def test_rawrequest_builtin_is_not_flagged_as_unescaped() -> None:
    """A GET's ${input.rawRequest} is a Genesys built-in, not user data to escape."""
    from app.gx.contracts import _assert_inputs_are_escaped

    ok = {
        "config": {
            "request": {
                "requestUrlTemplate": 'https://x/y?a=$esc.url("${input.a}")',
                "requestTemplate": "${input.rawRequest}",
            }
        }
    }

    _assert_inputs_are_escaped(ok, "ok")  # must not raise


@pytest.mark.parametrize("slug", [a.slug for a in ACTIONS])
def test_every_referenced_input_is_required(slug: str) -> None:
    """An input a template references must be required: Velocity renders an unsupplied
    optional as the literal ${input.X} and breaks the request. The generator runs this,
    so a pass here means it held for every real contract."""
    from app.gx.contracts import _assert_referenced_inputs_are_required

    _assert_referenced_inputs_are_required(build_all()[slug], slug)


@pytest.mark.parametrize(
    ("slug", "field_name"),
    [
        ("csat", "comment"),
        ("csat", "conversation_ref"),
        ("device-action", "params"),
        ("order-action", "params"),
        ("interaction-event", "kind"),
    ],
)
def test_previously_optional_referenced_inputs_are_now_required(
    slug: str, field_name: str
) -> None:
    """These were optional-but-referenced — the exact bug (csat comment / conversation_ref
    errored on import when omitted). They must now be required."""
    required = build_all()[slug]["contract"]["input"]["inputSchema"]["required"]

    assert field_name in required


def test_generation_refuses_an_optional_referenced_input() -> None:
    """The rule, pinned: a template reference to a field the schema marks optional must
    fail generation, not surface at import."""
    from app.gx.contracts import (
        OptionalReferencedInput,
        _assert_referenced_inputs_are_required,
    )

    bad = {
        "config": {
            "request": {
                "requestUrlTemplate": "https://x/y",
                "requestTemplate": '{"comment": "$esc.jsonString("${input.comment}")"}',
            }
        },
        "contract": {"input": {"inputSchema": {"required": ["identifier"]}}},
    }

    with pytest.raises(OptionalReferencedInput, match="comment"):
        _assert_referenced_inputs_are_required(bad, "bad")


def test_contracts_are_valid_json_on_disk() -> None:
    for action in ACTIONS:
        payload: dict[str, Any] = json.loads((CONTRACTS_DIR / f"{action.slug}.json").read_text())
        assert payload["contract"]["input"]["inputSchema"]["type"] == "object"
        assert payload["contract"]["output"]["successSchema"]["type"] in {"object", "array"}
