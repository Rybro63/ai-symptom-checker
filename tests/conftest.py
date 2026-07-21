"""Shared test fixtures: in-memory DynamoDB (moto) and a mocked Claude client."""
import json
import os
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DYNAMODB_TABLE_NAME", "symptom-checks")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def dynamo_table():
    """Spin up an in-memory DynamoDB table matching template.yaml."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="symptom-checks",
            AttributeDefinitions=[
                {"AttributeName": "check_id", "AttributeType": "S"},
                {"AttributeName": "entity", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "check_id", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by-date",
                    "KeySchema": [
                        {"AttributeName": "entity", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield


def make_claude_response(payload: dict) -> MagicMock:
    """Build a fake anthropic Message whose text content is the given JSON."""
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    message = MagicMock()
    message.content = [block]
    return message


HIGH_CONFIDENCE_PAYLOAD = {
    "triage_level": "urgent",
    "triage_rationale": "Presentation is consistent with possible appendicitis.",
    "possible_conditions": [
        {
            "name": "Appendicitis",
            "confidence": 0.7,
            "reasoning": "RLQ pain with fever and nausea.",
            "common": True,
        },
        {
            "name": "Gastroenteritis",
            "confidence": 0.4,
            "reasoning": "Nausea and abdominal pain are common features.",
            "common": True,
        },
    ],
    "red_flags": ["Rigid abdomen", "High fever above 103F", "Pain migrating to RLQ"],
    "self_care_advice": None,
}

LOW_CONFIDENCE_PAYLOAD = {
    "triage_level": "self_care",
    "triage_rationale": "Vague symptoms with no clear pattern.",
    "possible_conditions": [
        {
            "name": "Viral syndrome",
            "confidence": 0.2,
            "reasoning": "Nonspecific fatigue.",
            "common": True,
        }
    ],
    "red_flags": [],
    "self_care_advice": "Rest and hydrate.",
}

LOW_CONFIDENCE_EMERGENCY_PAYLOAD = {
    "triage_level": "emergency",
    "triage_rationale": "Chest pain with shortness of breath requires immediate care.",
    "possible_conditions": [
        {
            "name": "Acute coronary syndrome",
            "confidence": 0.3,
            "reasoning": "Cannot be ruled out from text alone.",
            "common": False,
        }
    ],
    "red_flags": ["Crushing chest pain", "Pain radiating to arm"],
    "self_care_advice": None,
}


TEST_USER = "test-user-sub-1234"
OTHER_USER = "other-user-sub-5678"


@pytest.fixture(autouse=True)
def as_test_user():
    """Authenticate all requests as TEST_USER by overriding the auth dependency."""
    from src.app.main import app
    from src.app.auth import get_current_user_id

    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mock_claude(request):
    """Patch the Anthropic client to return a canned payload.

    Parametrize indirectly with one of the *_PAYLOAD dicts; defaults to
    HIGH_CONFIDENCE_PAYLOAD.
    """
    payload = getattr(request, "param", HIGH_CONFIDENCE_PAYLOAD)
    with patch("src.app.claude_client.anthropic.Anthropic") as mock_cls:
        instance = mock_cls.return_value
        instance.messages.create.return_value = make_claude_response(payload)
        yield instance
