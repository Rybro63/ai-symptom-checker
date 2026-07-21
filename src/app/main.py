"""Symptom Checker API — FastAPI app with AWS Lambda adapter.

Endpoints:
  POST /v1/checks        Run an AI symptom assessment and persist it
  GET  /v1/checks/{id}   Retrieve a past assessment
  GET  /v1/checks        List past assessments (paginated, newest first)
  GET  /health           Liveness probe
"""
import logging
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from . import db
from .auth import get_current_user_id
from .claude_client import AnalysisError, analyze_symptoms
from .models import (
    HistoryResponse,
    SymptomCheckRecord,
    SymptomCheckRequest,
    SymptomCheckResponse,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Symptom Checker API",
    version="1.0.0",
    description=(
        "Educational symptom triage powered by Claude, with a "
        "confidence-threshold inference layer and DynamoDB-backed history. "
        "Not a medical device; not a substitute for professional care."
    ),
)

# Allow browser-based frontends (local dev + deployed) to call this API.
# Handles the preflight OPTIONS request that browsers send before a POST.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/v1/checks",
    response_model=SymptomCheckResponse,
    status_code=201,
    tags=["checks"],
)
def create_check(
    payload: SymptomCheckRequest,
    user_id: str = Depends(get_current_user_id),
) -> SymptomCheckResponse:
    """Run an AI-powered triage assessment for the given symptoms."""
    try:
        result = analyze_symptoms(payload)
    except AnalysisError as exc:
        logger.error("Analysis failed: %s", exc)
        raise HTTPException(
            status_code=502, detail="The analysis engine returned an invalid response."
        ) from exc

    record = SymptomCheckRecord(request=payload, result=result)
    db.save_check(record, user_id)
    logger.info(
        "Saved check %s (triage=%s, low_confidence=%s)",
        record.check_id,
        result.triage_level.value,
        result.low_confidence,
    )
    return SymptomCheckResponse(check_id=record.check_id, result=result)


@app.get("/v1/checks/{check_id}", response_model=SymptomCheckRecord, tags=["checks"])
def get_check(
    check_id: str,
    user_id: str = Depends(get_current_user_id),
) -> SymptomCheckRecord:
    """Retrieve a previously completed assessment by id."""
    record = db.get_check(check_id, user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Check not found")
    return record


@app.get("/v1/checks", response_model=HistoryResponse, tags=["checks"])
def list_checks(
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    user_id: str = Depends(get_current_user_id),
) -> HistoryResponse:
    """List past assessments, newest first."""
    records, next_cursor = db.list_checks(user_id, limit=limit, cursor=cursor)
    return HistoryResponse(
        items=records, count=len(records), last_evaluated_key=next_cursor
    )


# AWS Lambda entrypoint (referenced by template.yaml)
handler = Mangum(app)
