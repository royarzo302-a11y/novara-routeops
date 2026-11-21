"""Evaluate the committed synthetic header corpus. Baseline is always offline."""

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import median

from app.ai.headers import (
    PROMPT_VERSION,
    REGION,
    BedrockHeaderInterpreter,
    HeaderInput,
    HeaderProposal,
    ProposalError,
    baseline_proposal,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "evals/headers/cases.json"


def score(rows):
    correct = sum(r["correct"] for r in rows)
    predicted = sum(r["predicted"] for r in rows)
    expected = sum(r["expected"] for r in rows)
    return {
        "cases": len(rows),
        "correct_mappings": correct,
        "predicted_mappings": predicted,
        "expected_mappings": expected,
        "precision": correct / predicted if predicted else None,
        "recall": correct / expected if expected else None,
        "exact_match_rate": sum(r["exact"] for r in rows) / len(rows) if rows else None,
        "wrong_mappings": predicted - correct,
        "missed_mappings": expected - correct,
        "errors": sum(r["error"] is not None for r in rows),
        "median_latency_ms": median(r["latency_ms"] for r in rows) if rows else None,
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
    }


def evaluate(cases, proposer):
    rows = []
    for case in cases:
        source = HeaderInput(headers=case["headers"])
        error = None
        try:
            result = proposer(source)
            proposal = result.proposal
        except ProposalError as exc:
            result, proposal, error = exc, HeaderProposal(mappings=()), exc.code
        predicted = {(m.column, m.field) for m in proposal.mappings}
        expected = {(m["column"], m["field"]) for m in case["expected"]}
        rows.append(
            {
                "id": case["id"],
                "split": case["split"],
                "cohort": case["cohort"],
                "correct": len(predicted & expected),
                "predicted": len(predicted),
                "expected": len(expected),
                "exact": predicted == expected and error is None,
                "error": error,
                "latency_ms": round(result.latency_ms, 3),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "proposal": proposal.model_dump(mode="json"),
            }
        )
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["baseline", "bedrock"], default="baseline")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="test")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model-id", default=os.getenv("NOVARA_BEDROCK_MODEL_ID", ""))
    parser.add_argument("--profile", default="novara-routeops")
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    proposer = baseline_proposal
    if args.provider == "bedrock":
        if not args.allow_paid or not args.model_id:
            parser.error("Bedrock requires --allow-paid and an explicit --model-id")
        try:
            proposer = BedrockHeaderInterpreter.from_profile(args.model_id, args.profile).propose
        except Exception:
            parser.error("Bedrock configuration unavailable; check model ID, profile and ai extra")
    raw = CORPUS.read_bytes()
    corpus = json.loads(raw)
    cases = [c for c in corpus["cases"] if args.split == "all" or c["split"] == args.split]
    if args.limit is not None:
        cases = cases[: args.limit]
    rows = evaluate(cases, proposer)
    cohorts = defaultdict(list)
    for row in rows:
        cohorts[row["cohort"]].append(row)
    report = {
        "dataset_version": corpus["version"],
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "provider": args.provider,
        "model_id": args.model_id if args.provider == "bedrock" else None,
        "region": REGION if args.provider == "bedrock" else None,
        "prompt_version": PROMPT_VERSION if args.provider == "bedrock" else None,
        "split": args.split,
        "max_output_tokens": 1024 if args.provider == "bedrock" else None,
        "temperature": 0 if args.provider == "bedrock" else None,
        "estimated_cost_usd": None,
        "cost_note": "Not estimated: apply verified model rates to measured token counts.",
        "summary": score(rows),
        "cohorts": {k: score(v) for k, v in cohorts.items()},
        "cases": rows,
    }
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))
    return 1 if report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
