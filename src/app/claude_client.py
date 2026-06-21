"""Claude-powered symptom analysis engine.

Sends a structured prompt to the Anthropic API and parses the response into
a validated SymptomCheckResult. Implements a confidence-threshold inference
layer: when the model's top-condition confidence is below the configured
threshold, the differential is suppressed and the user is directed to a
clinician rather than shown a low-reliability guess.
"""
import json
import logging

import anthropic

from .config import get_settings
from .models import (
    PossibleCondition,
    SymptomCheckRequest,
    SymptomCheckResult,
    TriageLevel,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a clinical triage assistant supporting an educational \
symptom-checker application. You are NOT providing a diagnosis. Given a patient's \
symptom description and demographics, produce a conservative triage assessment.

Rules:
- Always err toward the safer (more urgent) triage level when uncertain.
- Any mention of chest pain with shortness of breath, signs of stroke, anaphylaxis, \
uncontrolled bleeding, or suicidal ideation must be triaged as "emergency".
- Confidence values must honestly reflect diagnostic uncertainty from a brief \
text description; they should rarely exceed 0.85.
- List 1-5 possible conditions, most likely first.
- red_flags must be specific, observable warning signs relevant to this presentation.

Respond ONLY with a JSON object matching this schema, no markdown fences, no preamble:
{
  "triage_level": "emergency" | "urgent" | "routine" | "self_care",
  "triage_rationale": "<1-3 sentences>",
  "possible_conditions": [
    {"name": "...", "confidence": 0.0-1.0, "reasoning": "...", "common": true|false}
  ],
  "red_flags": ["..."],
  "self_care_advice": "<string or null>"
}"""


class AnalysisError(Exception):
    """Raised when the model response cannot be parsed into a valid result."""


def _build_user_prompt(req: SymptomCheckRequest) -> str:
    parts = [
        f"Symptoms: {req.symptoms}",
        f"Age: {req.age}",
        f"Sex: {req.sex.value}",
    ]
    if req.duration_hours is not None:
        parts.append(f"Duration: {req.duration_hours} hours")
    if req.existing_conditions:
        parts.append(f"Existing conditions: {req.existing_conditions}")
    return "\n".join(parts)


def _parse_model_json(raw_text: str) -> dict:
    """Parse model output, tolerating accidental markdown fences."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"Model returned non-JSON output: {exc}") from exc


def analyze_symptoms(req: SymptomCheckRequest) -> SymptomCheckResult:
    """Run the Claude analysis and apply the confidence-threshold layer."""
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    message = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(req)}],
    )

    raw = "".join(block.text for block in message.content if block.type == "text")
    data = _parse_model_json(raw)

    try:
        conditions = [PossibleCondition(**c) for c in data.get("possible_conditions", [])]
        result = SymptomCheckResult(
            triage_level=TriageLevel(data["triage_level"]),
            triage_rationale=data["triage_rationale"],
            possible_conditions=conditions,
            red_flags=data.get("red_flags", []),
            self_care_advice=data.get("self_care_advice"),
        )
    except (KeyError, ValueError) as exc:
        raise AnalysisError(f"Model output failed validation: {exc}") from exc

    # --- Confidence-threshold inference layer -------------------------------
    # Never suppress an emergency/urgent triage signal: under-confidence about
    # *which* condition it is must not hide the fact that care is needed.
    top_confidence = max((c.confidence for c in result.possible_conditions), default=0.0)
    if (
        top_confidence < settings.confidence_threshold
        and result.triage_level in (TriageLevel.ROUTINE, TriageLevel.SELF_CARE)
    ):
        logger.info(
            "Top confidence %.2f below threshold %.2f; suppressing differential",
            top_confidence,
            settings.confidence_threshold,
        )
        result.low_confidence = True
        result.possible_conditions = []
        result.triage_level = TriageLevel.ROUTINE
        result.triage_rationale = (
            "The assessment confidence for this symptom description is too low "
            "to provide a reliable list of possible conditions. Please consult "
            "a healthcare professional for an in-person evaluation."
        )
        result.self_care_advice = None

    return result
