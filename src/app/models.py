"""Pydantic models for the Symptom Checker API."""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class TriageLevel(str, Enum):
    """Urgency classification for a symptom assessment."""

    EMERGENCY = "emergency"      # Call 911 / go to ER now
    URGENT = "urgent"            # See a doctor within 24 hours
    ROUTINE = "routine"          # Schedule a normal appointment
    SELF_CARE = "self_care"      # Manageable at home, monitor symptoms


class Sex(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class SymptomCheckRequest(BaseModel):
    """Incoming symptom check payload."""

    symptoms: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Free-text description of symptoms",
        examples=["Sharp pain in lower right abdomen for 6 hours, mild fever, nausea"],
    )
    age: int = Field(..., ge=0, le=120, description="Patient age in years")
    sex: Sex = Field(..., description="Biological sex (relevant for differential)")
    duration_hours: Optional[float] = Field(
        None, ge=0, description="How long symptoms have been present, in hours"
    )
    existing_conditions: Optional[str] = Field(
        None, max_length=500, description="Known conditions, e.g. 'type 2 diabetes, asthma'"
    )

    @field_validator("symptoms")
    @classmethod
    def symptoms_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("symptoms must not be blank")
        return v.strip()


class PossibleCondition(BaseModel):
    """A single condition in the differential, with model confidence."""

    name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    common: bool = Field(
        ..., description="Whether this is a common condition for this presentation"
    )


class SymptomCheckResult(BaseModel):
    """Structured assessment returned by the analysis engine."""

    triage_level: TriageLevel
    triage_rationale: str
    possible_conditions: list[PossibleCondition]
    red_flags: list[str] = Field(
        default_factory=list,
        description="Warning signs that should prompt immediate care if they appear",
    )
    self_care_advice: Optional[str] = None
    low_confidence: bool = Field(
        False,
        description=(
            "True when the model's top confidence falls below the inference "
            "threshold; the API recommends professional evaluation instead of "
            "surfacing an unreliable differential."
        ),
    )


class SymptomCheckRecord(BaseModel):
    """Persisted record of a completed check (DynamoDB item)."""

    check_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    request: SymptomCheckRequest
    result: SymptomCheckResult


class SymptomCheckResponse(BaseModel):
    """API response envelope."""

    check_id: str
    result: SymptomCheckResult
    disclaimer: str = (
        "This tool provides educational information only and is not a medical "
        "diagnosis. Always consult a qualified healthcare professional. If this "
        "is an emergency, call 911."
    )


class HistoryResponse(BaseModel):
    """Paginated history listing."""

    items: list[SymptomCheckRecord]
    count: int
    last_evaluated_key: Optional[str] = None
