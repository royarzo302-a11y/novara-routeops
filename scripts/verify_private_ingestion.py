"""Read-only, aggregate-only verification on DEVELOPMENT historical packages.

Reserved folders are rejected before opening a file. Never print paths, cells or exceptions.
No database, fixture generation, external service or solver is used by this program.
"""

import argparse
import hashlib
import io
import json
import re
import sys
import warnings
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.ingestion.excel import normalize  # noqa: E402
from app.ingestion.real_excel import parse_real_excel  # noqa: E402
from app.models.ingestion import CustomerCode, DocumentRole  # noqa: E402
from app.services.reconciliation import reconcile  # noqa: E402

VALIDATION_CUTOFF = date(2026, 10, 17)


def archive_day(path: Path, root: Path) -> date | None:
    """Use directory context, never the workbook filename or a cached TODAY() value."""
    for part in path.relative_to(root).parts[:-1]:
        for pattern, iso in [
            (r"(?<!\d)(20\d{2})[-_. /](\d{1,2})[-_. /](\d{1,2})(?!\d)", True),
            (r"(?<!\d)(\d{1,2})[-_. /](\d{1,2})[-_. /](20\d{2}|\d{2})(?!\d)", False),
        ]:
            match = re.search(pattern, part)
            if match:
                a, b, c = (int(v) for v in match.groups())
                try:
                    return date(a, b, c) if iso else date(c if c >= 2000 else 2000 + c, b, a)
                except ValueError:
                    continue
    return None


def file_role(path, root):
    parts = [normalize(p) for p in path.relative_to(root).parts[:-1]]
    if any(p.startswith("rutas") for p in parts):
        return DocumentRole.ORIGINAL
    if any("sms" in p for p in parts):
        return None
    # Only the exterior operator workbook is an internal list.
    return DocumentRole.INTERNAL if len(parts) <= 2 else None


def eligible_files(root: Path):
    selected, counts = [], Counter()
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        day = archive_day(path, root)
        role = file_role(path, root)
        if day and day >= VALIDATION_CUTOFF:
            counts["reserved_files_not_opened"] += 1
            if role == DocumentRole.ORIGINAL and path.suffix.lower() == ".xlsx":
                counts["reserved_originals_not_opened"] += 1
            continue
        if day is None:
            counts["files_without_verified_archive_date_skipped"] += 1
            continue
        if path.suffix.lower() != ".xlsx" or role is None:
            counts["non_roster_files_skipped"] += 1
            continue
        customer = (
            CustomerCode.LO_BLANCO
            if any(
                "lo blanco" in normalize(p) or "loblanco" in normalize(p)
                for p in path.relative_to(root).parts[:-1]
            )
            else CustomerCode.GRAN_AMERICA
        )
        selected.append((path, day, customer, role))
    return selected, counts


def verify(root: Path):
    selected, scope = eligible_files(root)
    results = defaultdict(dict)
    counts, issues, differences, enrichments, directions, customers = (
        Counter(),
        Counter(),
        Counter(),
        Counter(),
        Counter(),
        Counter(),
    )
    unchanged = True
    for path, day, customer, role in selected:
        if day >= VALIDATION_CUTOFF:
            raise RuntimeError("Reserved scope rejected")
        before = path.read_bytes()
        try:
            # Discard all third-party output; only explicit aggregate counters leave this process.
            with (
                warnings.catch_warnings(),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                warnings.simplefilter("ignore")
                result = parse_real_excel(before, customer, role, archive_date=day)
            counts[f"{role}_books_opened"] += 1
            if result.requests:
                counts[f"{role}_books_interpreted"] += 1
                customers[f"{customer}:{role}"] += 1
            else:
                counts[f"{role}_books_without_requests"] += 1
            counts[f"{role}_requests"] += len(result.requests)
            counts[f"{role}_quarantined_rows"] += len(result.unclassified_rows)
            counts[f"{role}_pending_review"] += result.batch.pending_review
            counts[f"{role}_unclassified_sheets"] += sum(
                s.review_required for s in result.batch.sheets
            )
            issues.update(i.code for r in result.requests for i in r.issues)
            directions.update(f"{role}:{r.direction}" for r in result.requests)
            results[(day, customer)][role] = result
        except Exception:
            counts[f"{role}_books_failed"] += 1
        finally:
            unchanged &= (
                hashlib.sha256(before).digest() == hashlib.sha256(path.read_bytes()).digest()
            )
    for pair in results.values():
        if set(pair) != {DocumentRole.ORIGINAL, DocumentRole.INTERNAL}:
            counts["unpaired_packages"] += 1
            continue
        report = reconcile(pair[DocumentRole.ORIGINAL], pair[DocumentRole.INTERNAL])
        counts["reconciled_packages"] += 1
        counts["identity_matches"] += len(report.matches)
        counts["provisional_matches"] += sum(m.provisional for m in report.matches)
        counts["unmatched_original_requests"] += len(report.unmatched_original_ids)
        counts["unmatched_internal_requests"] += len(report.unmatched_internal_ids)
        counts["ambiguous_identity_groups"] += len(report.ambiguous_groups)
        counts["original_rows_in_ambiguous_groups"] += sum(
            len(g["original_ids"]) for g in report.ambiguous_groups
        )
        counts["internal_rows_in_ambiguous_groups"] += sum(
            len(g["internal_ids"]) for g in report.ambiguous_groups
        )
        differences.update(report.difference_counts)
        enrichments.update(report.enrichment_counts)
    return {
        "scope": dict(scope),
        "counts": dict(counts),
        "by_customer": dict(customers),
        "directions": dict(directions),
        "issue_counts": dict(issues),
        "reconciliation_differences": dict(differences),
        "enriched_fields": dict(enrichments),
        "originals_unchanged": unchanged,
        "reserved_workbooks_opened": 0,
        "database_writes": 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Aggregate-only local development verification")
    parser.add_argument("--root", type=Path, default=Path("data/real"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if not args.root.is_dir():
            raise ValueError("Missing dataset")
        # Never put an output into the source dataset, even when the caller asks for it.
        if args.output and args.output.resolve().is_relative_to(args.root.resolve()):
            raise ValueError("Output inside private source tree")
        result = verify(args.root)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(text + "\n")
        print(text)
        return (
            0
            if result["originals_unchanged"]
            and not any(v for k, v in result["counts"].items() if k.endswith("books_failed"))
            else 1
        )
    except Exception:
        print(json.dumps({"verification_failed": True, "details_withheld": True}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
