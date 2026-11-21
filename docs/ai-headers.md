# Header interpretation with Amazon Bedrock

[Español](ai-headers.es.md) · [Case study](portfolio.md)

## Research question and current status

Can a constrained model recover mappings for unfamiliar column labels while preserving the precision of deterministic profiles? The optional adapter and evaluation harness are implemented. **Live inference and model-quality results are pending.** No improvement over the baseline is claimed.

The operational parser remains deterministic. The AI module is not mounted as an API endpoint and cannot write to ingestion, accept a proposal, approve a location or dispatch a vehicle. The legacy `HeaderInterpreter` protocol is an older extension placeholder; the new experiment uses a separate header-only input to avoid passing rows.

## Contract and failure behavior

Input is 1–30 labels, each at most 120 characters. Row values and workbook uploads are not accepted. Output is a JSON object containing zero-based column/field pairs from an allowlist of 11 fields. Repeated columns, repeated fields, out-of-range indexes, coercible-but-wrong types and extra properties are rejected. Every validated proposal carries `requires_human_review=true`.

The system prompt treats labels as untrusted data. No tools are registered. Non-text blocks, tool-use requests, truncated/filtered responses, malformed JSON and schema violations fail closed. Provider failures are recorded with fixed error codes, without exposing request text or provider diagnostics. There is no silent fallback that could be counted as a model success. Schema validation limits structural errors; it does not prove a semantically correct mapping or universal prompt-injection resistance.

## Dataset and baseline

`evals/headers/cases.json` contains 36 hand-authored synthetic cases, no passenger rows and no extracts from private workbooks. Version: `headers-synthetic-v1`.

| Split | Cohorts | Cases |
| --- | --- | --- |
| Development | Known vocabulary, noisy labels | 12 |
| Test | New Spanish expressions, English, ambiguity, adversarial instructions | 24 |

The test set is public and intentionally stresses unknown vocabulary. It is not a representative sample of operational traffic or a blind benchmark. Both labels and expected mappings can be inspected. If results are used to tune prompts, collect a new independently labelled holdout before making generalization claims.

The baseline pools the current v2 customer-profile vocabulary and abstains on repeated target fields. It evaluates column mapping only, not the entire workbook recognizer. In the committed test run:

| Metric | Offline baseline |
| --- | --- |
| Correct / predicted / expected mappings | 13 / 13 / 51 |
| Precision | 100% of the 13 emitted mappings |
| Recall | 25.49% |
| Exact case match | 50% (12/24) |
| Wrong mappings / missed mappings / errors | 0 / 38 / 0 |
| Network requests / tokens | 0 / 0 |

[Machine-readable report](../evals/headers/baseline-test.json). Latency in that report is a local measurement and varies between runs. The English and novel-expression cohorts each have zero recall, showing the deliberate vocabulary gap. Known-label quality must be checked on the development split as well; a global score can hide regressions by cohort.

## Reproduce without AWS

```bash
uv sync --frozen
uv run --frozen python scripts/evaluate_headers.py --split test
uv run --frozen python scripts/evaluate_headers.py --split dev
```

The evaluator emits exact match, micro-precision/recall, wrong/missed mappings, error counts, per-cohort results, latency and token totals. Undefined precision is `null` when there are no predictions. Failed responses contribute missing mappings and never count as exact success, including cases with empty expected mappings.

## Optional live evaluation (not executed)

Install `uv sync --frozen --extra ai`. The implementation uses boto3 `bedrock-runtime.converse`, an explicit `maxTokens=1024`, `temperature=0`, 5-second connect and 30-second read timeouts, and adaptive retries capped at two total attempts. SDK compatibility is tested with a stubbed runtime. Real model support, entitlement and quality still require verification.

The project's selected Region is fixed to `us-east-2`. Only direct foundation-model IDs from the provider allowlist are accepted. Geographic/global inference profiles and ARNs are rejected; no cross-Region fallback is attempted. The SDK uses a local AWS profile rather than static credentials in the repository. Model listing alone does not establish invocation access.

After verifying an accessible in-region model and explicitly approving the run cost:

```bash
uv run --frozen --extra ai python scripts/evaluate_headers.py \
  --provider bedrock --model-id YOUR_IN_REGION_MODEL_ID \
  --profile novara-routeops --allow-paid --split dev --limit 1 \
  --output evals/runs/bedrock-smoke.json
```

Then run the same frozen test split for comparison. Avoid tuning against test results. A real run can incur model charges; `--limit` caps cases but is not a dollar-spend cap. Retries may generate additional attempts. No IAM policies, model subscriptions or paid services are activated by the evaluation setup. Effective runtime access must already be available.

Cost is left `null`: the report contains observed input/output token counts, but no invented prices. Calculate an estimate from verified model-specific rates and label it as an estimate; use AWS billing for billed cost. Model invocation logging, if enabled in the project, can store prompt content. This tool deliberately runs only the committed synthetic corpus; do not substitute personal data.

## Decision before integration

A live comparison must demonstrate improved recall on novel/English labels, no regression on known labels, acceptable precision and explicit review of every false positive. Examine adversarial cases and provider/schema failures separately. Choose numeric release thresholds before the paid test run based on the operator's error tolerance. This small corpus cannot establish operational safety. Next integration work is a proposal-review screen and explicit operator acceptance with provenance; neither is implemented yet.

References: [Converse API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html), [Python SDK](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime/client/converse.html).
