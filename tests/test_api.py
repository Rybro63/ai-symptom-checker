"""Integration tests for the Symptom Checker API (mocked Claude + moto DynamoDB)."""
import pytest
from fastapi.testclient import TestClient

from src.app.main import app
from tests import conftest as fx

client = TestClient(app)

VALID_PAYLOAD = {
    "symptoms": "Sharp pain in lower right abdomen for 6 hours, mild fever, nausea",
    "age": 21,
    "sex": "male",
    "duration_hours": 6,
}


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_check_happy_path(dynamo_table, mock_claude):
    resp = client.post("/v1/checks", json=VALID_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["check_id"]
    assert "not a medical diagnosis" in body["disclaimer"]
    result = body["result"]
    assert result["triage_level"] == "urgent"
    assert result["low_confidence"] is False
    assert result["possible_conditions"][0]["name"] == "Appendicitis"
    assert 0.0 <= result["possible_conditions"][0]["confidence"] <= 1.0
    assert len(result["red_flags"]) == 3


@pytest.mark.parametrize("mock_claude", [fx.LOW_CONFIDENCE_PAYLOAD], indirect=True)
def test_confidence_threshold_suppresses_differential(dynamo_table, mock_claude):
    """Below-threshold confidence on a non-urgent triage hides the guess list."""
    resp = client.post("/v1/checks", json=VALID_PAYLOAD)
    assert resp.status_code == 201
    result = resp.json()["result"]
    assert result["low_confidence"] is True
    assert result["possible_conditions"] == []
    assert result["triage_level"] == "routine"
    assert "consult a healthcare professional" in result["triage_rationale"]


@pytest.mark.parametrize(
    "mock_claude", [fx.LOW_CONFIDENCE_EMERGENCY_PAYLOAD], indirect=True
)
def test_confidence_threshold_never_suppresses_emergency(dynamo_table, mock_claude):
    """Low confidence must NOT downgrade or hide an emergency triage signal."""
    resp = client.post("/v1/checks", json=VALID_PAYLOAD)
    assert resp.status_code == 201
    result = resp.json()["result"]
    assert result["triage_level"] == "emergency"
    assert result["low_confidence"] is False
    assert len(result["possible_conditions"]) == 1


@pytest.mark.parametrize(
    "bad_payload,expected_loc",
    [
        ({**VALID_PAYLOAD, "symptoms": "ouch"}, "symptoms"),       # too short
        ({**VALID_PAYLOAD, "age": 200}, "age"),                    # out of range
        ({**VALID_PAYLOAD, "sex": "robot"}, "sex"),                # bad enum
        ({k: v for k, v in VALID_PAYLOAD.items() if k != "age"}, "age"),  # missing
    ],
)
def test_validation_errors(bad_payload, expected_loc):
    resp = client.post("/v1/checks", json=bad_payload)
    assert resp.status_code == 422
    assert any(expected_loc in str(err["loc"]) for err in resp.json()["detail"])


def test_get_check_roundtrip(dynamo_table, mock_claude):
    created = client.post("/v1/checks", json=VALID_PAYLOAD).json()
    check_id = created["check_id"]

    resp = client.get(f"/v1/checks/{check_id}")
    assert resp.status_code == 200
    record = resp.json()
    assert record["check_id"] == check_id
    assert record["request"]["age"] == 21
    assert record["result"]["triage_level"] == "urgent"


def test_get_check_404(dynamo_table):
    resp = client.get("/v1/checks/does-not-exist")
    assert resp.status_code == 404


def test_list_checks_newest_first_and_paginated(dynamo_table, mock_claude):
    ids = [client.post("/v1/checks", json=VALID_PAYLOAD).json()["check_id"] for _ in range(3)]

    page1 = client.get("/v1/checks", params={"limit": 2}).json()
    assert page1["count"] == 2
    assert page1["last_evaluated_key"] is not None
    # Newest first: the last-created id should appear first
    assert page1["items"][0]["check_id"] == ids[-1]

    page2 = client.get(
        "/v1/checks", params={"limit": 2, "cursor": page1["last_evaluated_key"]}
    ).json()
    assert page2["count"] == 1

    seen = {i["check_id"] for i in page1["items"]} | {i["check_id"] for i in page2["items"]}
    assert seen == set(ids)


def test_unauthenticated_request_is_rejected(dynamo_table):
    """Without auth claims (no override), protected endpoints return 401."""
    from src.app.main import app
    from src.app.auth import get_current_user_id

    app.dependency_overrides.pop(get_current_user_id, None)
    resp = client.get("/v1/checks")
    assert resp.status_code == 401


def test_users_cannot_see_each_others_checks(dynamo_table, mock_claude):
    """A check created by one user must be invisible to another."""
    from src.app.main import app
    from src.app.auth import get_current_user_id

    created = client.post("/v1/checks", json=VALID_PAYLOAD).json()
    check_id = created["check_id"]

    # Switch identity to a different user
    app.dependency_overrides[get_current_user_id] = lambda: fx.OTHER_USER

    assert client.get(f"/v1/checks/{check_id}").status_code == 404
    assert client.get("/v1/checks").json()["count"] == 0


def test_claude_garbage_output_returns_502(dynamo_table):
    from unittest.mock import MagicMock, patch

    block = MagicMock()
    block.type = "text"
    block.text = "I'm sorry, I can't produce JSON today."
    message = MagicMock()
    message.content = [block]

    with patch("src.app.claude_client.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = message
        resp = client.post("/v1/checks", json=VALID_PAYLOAD)
    assert resp.status_code == 502
