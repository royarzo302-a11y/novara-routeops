# Portfolio case study: Novara RouteOps

[Español](portfolio.es.md) · [Project overview](../README.md)

## Problem and users

An employee-transport operator receives spreadsheets with changing column names, incomplete locations and multiple shift times. Dispatch decisions depend on fleet capacity, driver availability, arrival windows and trustworthy source data. A plausible route built from an incorrectly interpreted spreadsheet is an unsafe outcome.

The implemented workflow makes ambiguity visible before planning. The public demonstration uses fictitious passengers and public reference locations; private operational files are not part of the deliverable.

## Product walkthrough

1. Import the supplied spreadsheet and inspect its source rows and validation findings.
2. Correct a deliberately missing municipality and approve the pickup locations.
3. Prepare the shared fleet, destination terminals, travel matrix and operating constraints.
4. Compute a joint inbound preview and inspect assigned and unassigned requests.
5. Export the plan with route times, identifiers and a separate assumptions sheet.

The hosted profile fixes the operational factors and isolates temporary browser sessions. The local operator profile supports broader configuration. These are different product modes with different data permissions.

## Engineering work demonstrated

| Concern | Implementation | Evidence |
| --- | --- | --- |
| Input reliability | Deterministic profiles, formula rejection, bounded workbook handling, provenance | Ingestion tests and synthetic workbook builders |
| State consistency | Human corrections, stale-plan invalidation, scoped database transactions | API, ingestion-review and preparation tests |
| Optimization | CP-SAT with capacity, shift windows and sequential trips | Joint-planning tests; explicit partial/search-limit outcomes |
| Application delivery | React + FastAPI, single-origin container profile, isolated demo sessions | Hosted integration test and browser scenario |
| AI integration | Optional Bedrock Converse client with strict output validation | Adapter tests; malformed-output and error-path tests |
| Evaluation | Versioned labels, development/test split, baseline and cohort metrics | `evals/headers/` and `scripts/evaluate_headers.py` |
| Reproducibility | Locked dependencies, local Docker verification, CI definitions | Lockfiles, Dockerfile and workflow files |

## Observed evidence

The pre-portfolio Linux container rehearsal completed login, two synthetic imports, municipality correction, fixed-factor review, joint planning, map display and Excel export. One observed run assigned 16 requests across 5 trips with none unassigned, returned health after 7.25 seconds and completed the planning interaction in 3292 ms. A post-run memory sample was 173.1 MiB. This is one local Docker observation, not an AWS benchmark, peak-memory measurement or global-optimality claim.

The AI experiment has no live-model result yet. Its deterministic baseline is reproducible from the committed synthetic corpus. Passing mocked SDK tests does not establish model accuracy, prompt-injection resistance or economic value.

## Why this belongs in an AI engineering portfolio

It combines data contracts, backend/frontend integration, constrained optimization, cloud packaging and an evaluated model boundary. The model's proposed contribution is interpreting unfamiliar labels; validated business rules and the route solver retain responsibility for the transport result.

The key experiment is whether Bedrock improves recall on unfamiliar labels without increasing incorrect mappings. Exact-match, precision, recall, provider failures, latency and token counts are measured independently. The decision to integrate into the operator application depends on measured results, not the presence of an SDK dependency.

## Honest scope and remaining work

The application is a supervised prototype. Joint previews do not reserve dispatch resources, matrices do not contain live traffic, and one-process SQLite does not solve distributed concurrency. Cloud publication is pending. Real-model evaluation and a user interface for reviewing AI proposals remain future work. No production usage, business savings or model-quality improvement is claimed.

Development uses AI assistance. Portfolio ownership should be demonstrated by explaining the constraints, inspecting generated changes, reproducing results and defending the failure-handling decisions. Interview talking points: why row values are excluded from prompts, why ambiguous mappings abstain, why a timeout is different from proven infeasibility, and why preview plans require an operational confirmation boundary.

[Current verification and synthetic screenshots](portfolio-verification.md).
