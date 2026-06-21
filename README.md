# AI Symptom Checker API

An educational symptom-triage REST API powered by Claude, deployed serverlessly on AWS. Users submit a free-text symptom description plus basic demographics; the API returns a structured triage assessment (emergency / urgent / routine / self-care), a ranked differential with per-condition confidence scores, red-flag warning signs, and self-care guidance — with every assessment persisted to DynamoDB for retrieval.

> ⚠️ **Disclaimer:** This project is for educational purposes only. It is not a medical device and does not provide medical diagnoses. Always consult a qualified healthcare professional.

## Architecture

```
Client ──> API Gateway (HTTP API) ──> Lambda (FastAPI via Mangum) ──> Anthropic Claude API
                                            │
                                            └──> DynamoDB (assessment history, GSI for
                                                 reverse-chronological pagination)
```

**Key engineering decisions:**

- **Confidence-threshold inference layer** — the model returns a per-condition confidence score; when the top confidence falls below a configurable threshold (default 0.35) on a non-urgent triage, the API suppresses the differential entirely and directs the user to a clinician rather than surfacing an unreliable guess. Emergency/urgent triage signals are *never* suppressed — diagnostic uncertainty must not hide the need for care.
- **Safety-first prompting** — the system prompt enforces conservative triage (always err toward more urgent) and hard rules for red-flag presentations (chest pain + dyspnea, stroke signs, anaphylaxis → emergency).
- **Single-table DynamoDB design** — `check_id` partition key with a `by-date` GSI enabling newest-first, cursor-paginated history queries without scans.
- **Fully serverless & pay-per-use** — Lambda + HTTP API Gateway + on-demand DynamoDB; idle cost is ~$0.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/checks` | Run an AI triage assessment and persist it |
| `GET` | `/v1/checks/{id}` | Retrieve a past assessment |
| `GET` | `/v1/checks?limit=&cursor=` | List assessments, newest first, paginated |
| `GET` | `/health` | Liveness probe |
| `GET` | `/docs` | Interactive Swagger UI (auto-generated) |

### Example

```bash
curl -X POST "$API_URL/v1/checks" \
  -H "Content-Type: application/json" \
  -d '{
    "symptoms": "Sharp pain in lower right abdomen for 6 hours, mild fever, nausea",
    "age": 21,
    "sex": "male",
    "duration_hours": 6
  }'
```

```json
{
  "check_id": "1f0c5e6a-...",
  "result": {
    "triage_level": "urgent",
    "triage_rationale": "Presentation is consistent with possible appendicitis...",
    "possible_conditions": [
      {"name": "Appendicitis", "confidence": 0.7, "reasoning": "...", "common": true}
    ],
    "red_flags": ["Rigid abdomen", "High fever above 103F"],
    "self_care_advice": null,
    "low_confidence": false
  },
  "disclaimer": "This tool provides educational information only..."
}
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export ANTHROPIC_API_KEY=sk-ant-...   # from console.anthropic.com
export DYNAMODB_TABLE_NAME=symptom-checks
export AWS_REGION=us-east-1           # table must exist, or run tests instead

uvicorn src.app.main:app --reload
# open http://127.0.0.1:8000/docs
```

## Tests

12 tests covering the happy path, the confidence-threshold layer (including the emergency-never-suppressed invariant), request validation, DynamoDB round-trips, pagination ordering, and malformed-model-output handling. Claude is mocked; DynamoDB runs in-memory via moto.

```bash
python -m pytest tests/ -v
```

## Deploy to AWS

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full SAM-based walkthrough.

```bash
sam build
sam deploy --guided --parameter-overrides AnthropicApiKey=$ANTHROPIC_API_KEY
```

## Tech stack

Python 3.12 · FastAPI · Pydantic v2 · Anthropic Claude API · AWS Lambda · API Gateway (HTTP API) · DynamoDB · AWS SAM · pytest · moto
