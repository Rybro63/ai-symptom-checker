"""DynamoDB persistence for symptom check records (per-user).

Table design (single-table):
  PK: check_id (string)
  GSI "by-date": PK = entity ("USER#<user_id>"), SK = created_at
    -> enables per-user, reverse-chronological history listing.
"""
import json
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key

from .config import get_settings
from .models import SymptomCheckRecord


def _entity(user_id: str) -> str:
    return f"USER#{user_id}"


def _table():
    settings = get_settings()
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    return dynamodb.Table(settings.dynamodb_table_name)


def save_check(record: SymptomCheckRecord, user_id: str) -> None:
    """Persist a completed symptom check owned by user_id."""
    item = {
        "check_id": record.check_id,
        "entity": _entity(user_id),
        "created_at": record.created_at,
        # Store nested models as JSON strings to avoid float/Decimal friction
        "request": record.request.model_dump_json(),
        "result": record.result.model_dump_json(),
    }
    _table().put_item(Item=item)


def _item_to_record(item: dict) -> SymptomCheckRecord:
    return SymptomCheckRecord(
        check_id=item["check_id"],
        created_at=item["created_at"],
        request=json.loads(item["request"]),
        result=json.loads(item["result"]),
    )


def get_check(check_id: str, user_id: str) -> Optional[SymptomCheckRecord]:
    """Fetch a single check by id if it belongs to user_id, else None.

    Ownership is enforced here: a valid check_id belonging to another user
    returns None (surfacing as 404), never another user's data.
    """
    resp = _table().get_item(Key={"check_id": check_id})
    item = resp.get("Item")
    if not item or item.get("entity") != _entity(user_id):
        return None
    return _item_to_record(item)


def list_checks(
    user_id: str, limit: int = 20, cursor: Optional[str] = None
) -> tuple[list[SymptomCheckRecord], Optional[str]]:
    """List user_id's checks newest-first with cursor-based pagination."""
    kwargs = {
        "IndexName": "by-date",
        "KeyConditionExpression": Key("entity").eq(_entity(user_id)),
        "ScanIndexForward": False,  # newest first
        "Limit": limit,
    }
    if cursor:
        start_key = json.loads(cursor)
        kwargs["ExclusiveStartKey"] = {
            "entity": _entity(user_id),
            "created_at": start_key["created_at"],
            "check_id": start_key["check_id"],
        }

    resp = _table().query(**kwargs)
    records = [_item_to_record(i) for i in resp.get("Items", [])]
    lek = resp.get("LastEvaluatedKey")
    next_cursor = (
        json.dumps({"created_at": lek["created_at"], "check_id": lek["check_id"]})
        if lek
        else None
    )
    return records, next_cursor
