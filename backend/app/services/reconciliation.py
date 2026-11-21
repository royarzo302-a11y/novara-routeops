"""Reconciliation outputs contain opaque request IDs and field names, never personal values."""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from app.ingestion.excel import normalize
from app.ingestion.real_excel import employee_identity, normalize_phone
from app.models.ingestion import (
    DocumentRole,
    IngestionResult,
    ReconciliationReport,
    RecordMatch,
)
from app.models.schemas import ValidationStatus

COMPARE_FIELDS = (
    "employee_code",
    "name",
    "address",
    "commune",
    "phone",
    "service_date",
    "work_time",
    "end_time",
    "pickup_time",
    "arrival_time",
    "terminal_name",
)


def normalized(field, value):
    if value is None:
        return None
    if field == "employee_code":
        return employee_identity(value)
    if field == "phone":
        try:
            return normalize_phone(value)
        except ValueError:
            return None
    if isinstance(value, str):
        return normalize(value)
    return value.isoformat()


def identity(request):
    if request.employee_code:
        return "employee_code", employee_identity(request.employee_code)
    if request.name and request.phone:
        return "name_phone", normalize(request.name), request.phone
    if request.name and request.address:
        return "name_address", normalize(request.name), normalize(request.address)
    return "unlinked", request.id


def reconcile(original: IngestionResult, internal: IngestionResult) -> ReconciliationReport:
    a, b = original.batch, internal.batch
    if a.role != DocumentRole.ORIGINAL or b.role != DocumentRole.INTERNAL:
        raise ValueError("Se requiere una nómina original y una lista interna")
    if a.customer_id != b.customer_id:
        raise ValueError("No se concilian documentos de clientes diferentes")
    if a.archive_date and b.archive_date and a.archive_date != b.archive_date:
        raise ValueError("Los documentos pertenecen a jornadas archivadas diferentes")
    groups = defaultdict(lambda: [[], []])
    active_original = [r for r in original.requests if not r.excluded]
    active_internal = [r for r in internal.requests if not r.excluded]
    for side, requests in enumerate((active_original, active_internal)):
        for request in requests:
            # Dates are deliberately compared after linking within the explicitly selected package.
            groups[(request.direction, identity(request))][side].append(request)
    matches, unmatched_a, unmatched_b, ambiguous = [], [], [], []
    differences, enrichments = Counter(), Counter()
    for (_, key), (left, right) in groups.items():
        if len(left) > 1 or len(right) > 1:
            ambiguous.append(
                {"original_ids": [r.id for r in left], "internal_ids": [r.id for r in right]}
            )
        elif left and right:
            aa, bb = left[0], right[0]
            fields = [
                field
                for field in COMPARE_FIELDS
                if getattr(aa, field) is not None
                and (normalized(field, getattr(aa, field)) != normalized(field, getattr(bb, field)))
            ]
            added = [
                field
                for field in COMPARE_FIELDS
                if getattr(aa, field) is None and getattr(bb, field) is not None
            ]
            differences.update(fields)
            enrichments.update(added)
            matches.append(
                RecordMatch(
                    original_id=aa.id,
                    internal_id=bb.id,
                    identity_basis=key[0],
                    provisional=key[0] != "employee_code",
                    different_fields=fields,
                    enriched_fields=added,
                )
            )
        else:
            unmatched_a.extend(r.id for r in left)
            unmatched_b.extend(r.id for r in right)
    warnings = []
    if not a.archive_date or not b.archive_date:
        warnings.append("archive_scope_unverified")
    if any(
        r.validation_status == ValidationStatus.REVIEW for r in active_original + active_internal
    ):
        warnings.append("source_records_pending_review")
    if any(m.provisional for m in matches):
        warnings.append("fallback_identity_requires_confirmation")
    if any(s.review_required for s in a.sheets + b.sheets):
        warnings.append("unclassified_sheets")
    needs_review = bool(warnings or differences or unmatched_a or unmatched_b or ambiguous)
    return ReconciliationReport(
        id=str(uuid4()),
        original_batch_id=a.id,
        internal_batch_id=b.id,
        created_at=datetime.now(UTC),
        status="pending_review" if needs_review else "reconciled",
        original_records=len(active_original),
        internal_records=len(active_internal),
        matches=matches,
        unmatched_original_ids=unmatched_a,
        unmatched_internal_ids=unmatched_b,
        ambiguous_groups=ambiguous,
        difference_counts=dict(differences),
        enrichment_counts=dict(enrichments),
        warnings=warnings,
    )
