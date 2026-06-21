"""DynamoDB persistence for symptom check records.

Table design (single-table, simple):
  PK: check_id (string)
  GSI "by-date": PK = entity (constant "CHECK"), SK = created_at
    -> enables reverse-chronological history listing.
"""
import json
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key

from .config import get_settings
from .models import SymptomCheckRecord

_ENTITY = "CHECK"


def _table():
    settings = get_settings()
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    return dynamodb.Table(settings.dynamodb_table_name)


def save_check(record: SymptomCheckRecord) -> None:
    """Persist a completed symptom check."""
    item = {
        "check_id": record.check_id,
        "entity": _ENTITY,
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


def get_check(check_id: str) -> Optional[SymptomCheckRecord]:
    """Fetch a single check by id, or None if not found."""
    resp = _table().get_item(Key={"check_id": check_id})
    item = resp.get("Item")
    return _item_to_record(item) if item else None


def list_checks(
    limit: int = 20, cursor: Optional[str] = None
) -> tuple[list[SymptomCheckRecord], Optional[str]]:
    """List checks newest-first with cursor-based pagination.

    The cursor is an opaque JSON string produced by a previous call; pass it
    back unchanged to fetch the next page.
    """
    kwargs = {
        "IndexName": "by-date",
        "KeyConditionExpression": Key("entity").eq(_ENTITY),
        "ScanIndexForward": False,  # newest first
        "Limit": limit,
    }
    if cursor:
        start_key = json.loads(cursor)
        kwargs["ExclusiveStartKey"] = {
            "entity": _ENTITY,
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
