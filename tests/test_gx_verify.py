from fastapi.testclient import TestClient

from tests.test_gx_customer_context import assert_flat

SEEDED_PHONE = "+447700900000"
SEEDED_PIN = "24680"  # northwind pack: seed.verification.value_pattern (5 digits, BE-5)


def _verify(client: TestClient, auth: dict[str, str], **payload: str) -> dict:
    return client.post("/gx/verify-customer", json=payload, headers=auth).json()


def test_requires_api_key(client: TestClient) -> None:
    r = client.post(
        "/gx/verify-customer",
        json={"identifier": SEEDED_PHONE, "factor_type": "pin", "factor_value": SEEDED_PIN},
    )

    assert r.status_code == 401


def test_happy_path(client: TestClient, auth: dict[str, str], seeded_northwind: None) -> None:
    body = _verify(
        client, auth, identifier=SEEDED_PHONE, factor_type="pin", factor_value=SEEDED_PIN
    )

    assert body["verified"] is True
    assert body["party_id"]
    assert body["masked_name"]


def test_response_is_flat(client: TestClient, auth: dict[str, str], seeded_northwind: None) -> None:
    body = _verify(
        client, auth, identifier=SEEDED_PHONE, factor_type="pin", factor_value=SEEDED_PIN
    )

    assert_flat(body)


def test_masked_name_follows_tenant_config(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    context = client.get(
        "/gx/customer-context", params={"identifier": SEEDED_PHONE}, headers=auth
    ).json()
    body = _verify(
        client, auth, identifier=SEEDED_PHONE, factor_type="pin", factor_value=SEEDED_PIN
    )

    real_name = context["display_name"]
    masked = body["masked_name"]

    assert masked != real_name
    # reveal_chars: 1, mask_char: '*', mask_length: 3 → 'Anne Clark-Phillips' → 'A*** C***'
    assert masked == " ".join(token[0] + "***" for token in real_name.split())
    # The real name must not survive in the masked form.
    for token in real_name.split():
        assert token not in masked


def test_wrong_factor_is_false_without_detail(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    body = _verify(client, auth, identifier=SEEDED_PHONE, factor_type="pin", factor_value="0000")

    assert body["verified"] is False
    # No leak: a wrong factor must not confirm the subscriber exists.
    assert body["party_id"] == ""
    assert body["masked_name"] == ""


def test_wrong_factor_type_is_false(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    body = _verify(
        client, auth, identifier=SEEDED_PHONE, factor_type="dob", factor_value=SEEDED_PIN
    )

    assert body["verified"] is False


def test_unknown_identifier_is_false(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    body = _verify(
        client, auth, identifier="+447700900999", factor_type="pin", factor_value=SEEDED_PIN
    )

    assert body["verified"] is False


def test_unrecognized_identifier_is_false_not_500(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    body = _verify(client, auth, identifier="???", factor_type="pin", factor_value=SEEDED_PIN)

    assert body["verified"] is False


def test_normalizes_the_identifier_like_context_does(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    """A space-decoded '+' and a national number must verify too."""
    for identifier in (" 447700900000", "07700900000"):
        body = _verify(
            client, auth, identifier=identifier, factor_type="pin", factor_value=SEEDED_PIN
        )
        assert body["verified"] is True, identifier


def test_cross_tenant_verify_does_not_leak(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, seeded_acme: None
) -> None:
    r = client.post(
        "/gx/verify-customer",
        json={"identifier": SEEDED_PHONE, "factor_type": "pin", "factor_value": SEEDED_PIN},
        headers={**auth, "X-Tenant": "acme"},
    )

    assert r.status_code == 200
    assert r.json()["verified"] is False
