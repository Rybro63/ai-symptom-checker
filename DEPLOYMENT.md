# Deployment Guide — AWS SAM

This walks you from zero to a live API URL. Estimated time: 20–30 minutes the first time.

## Prerequisites

1. **AWS account** with an IAM user that has admin (or sufficient) permissions
2. **AWS CLI** installed and configured: `aws configure` (enter access key, secret, region `us-east-1`)
3. **AWS SAM CLI** installed — https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html
4. **Anthropic API key** — create one at https://console.anthropic.com (note: this is separate from a claude.ai subscription; the API is pay-per-token, and this project's usage will cost pennies)
5. **Docker** (optional but recommended — lets `sam build` compile dependencies in a Lambda-like container)

## Step 1 — Build

From the project root:

```bash
sam build
```

If you have Docker running, prefer:

```bash
sam build --use-container
```

This packages `src/` plus `src/requirements.txt` into a Lambda deployment artifact under `.aws-sam/`.

## Step 2 — Deploy (first time)

```bash
sam deploy --guided --parameter-overrides AnthropicApiKey=YOUR_ANTHROPIC_KEY
```

Answer the prompts:

- **Stack Name:** `symptom-checker`
- **AWS Region:** `us-east-1` (or your preference)
- **Confirm changes before deploy:** `y`
- **Allow SAM CLI IAM role creation:** `y`
- **Disable rollback:** `n`
- **SymptomCheckerFunction has no authentication. Is this okay?** `y` (it's a demo API; see Hardening below)
- **Save arguments to configuration file:** `y` — future deploys are just `sam deploy`

When it finishes, the **Outputs** section prints your `ApiUrl`. That's your live endpoint.

> The API key is passed as a CloudFormation parameter with `NoEcho: true`, so it won't appear in console output or the template. For a production system you'd move it to AWS Secrets Manager — a good talking point in interviews.

## Step 3 — Smoke test

```bash
export API_URL=https://xxxxxx.execute-api.us-east-1.amazonaws.com

curl "$API_URL/health"
# {"status":"ok"}

curl -X POST "$API_URL/v1/checks" \
  -H "Content-Type: application/json" \
  -d '{"symptoms":"Sore throat, mild fever, and fatigue for two days","age":21,"sex":"male"}'

curl "$API_URL/v1/checks?limit=5"
```

Also open `$API_URL/docs` in a browser for the interactive Swagger UI.

## Step 4 — Iterate

After code changes:

```bash
sam build && sam deploy
```

To view live logs:

```bash
sam logs --stack-name symptom-checker --tail
```

## Cost notes

- **Lambda + API Gateway + DynamoDB on-demand:** effectively $0 at portfolio-traffic levels (all have generous free tiers)
- **Anthropic API:** pay per token; a single assessment costs well under a cent with Sonnet
- Tear everything down anytime: `sam delete`

## Hardening ideas (great interview talking points)

- Move the Anthropic key to **Secrets Manager** and fetch at cold start
- Add **API Gateway usage plans / API keys** or Cognito auth
- Add **rate limiting** to prevent runaway LLM costs
- Emit **CloudWatch custom metrics** for triage-level distribution and low-confidence rate
- Add a **DynamoDB TTL attribute** to auto-expire old checks (privacy-friendly)
