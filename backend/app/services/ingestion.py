from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.ingestion.excel import normalize
from app.ingestion.real_excel import normalize_phone, validate_requests
from app.models.entities import (
    IngestionBatchRow,
    ReconciliationRow,
    TerminalRow,
    TransportRequestRow,
    UnclassifiedRowEntity,
)
from app.models.ingestion import (
    Correction,
    IngestionBatch,
    IngestionResult,
    Terminal,
    TransportRequest,
    UnclassifiedRow,
)
from app.models.schemas import ValidationStatus


def service_dates(requests):
    return sorted(
        {
            request.service_date
            for request in requests
            if request.service_date and request.direction == "inbound" and not request.excluded
        }
    )


def load_ingestion(db, row: IngestionBatchRow) -> IngestionResult:
    requests = [
        TransportRequest.model_validate(r.payload)
        for r in db.scalars(
            select(TransportRequestRow).where(TransportRequestRow.batch_id == row.id),
        )
    ]
    requests.sort(key=lambda r: (r.provenance.sheet_index, r.provenance.row))
    unknown = [
        UnclassifiedRow.model_validate(r.payload)
        for r in db.scalars(
            select(UnclassifiedRowEntity).where(UnclassifiedRowEntity.batch_id == row.id),
        )
    ]
    batch = IngestionBatch.model_validate(row.payload)
    batch.service_dates = service_dates(requests)
    return IngestionResult(
        batch=batch,
        requests=requests,
        unclassified_rows=unknown,
    )


def persist_ingestion(db, result: IngestionResult):
    batch = result.batch
    batch.service_dates = service_dates(result.requests)
    db.add(
        IngestionBatchRow(
            id=batch.id, customer_id=batch.customer_id, payload=batch.model_dump(mode="json")
        )
    )
    db.flush()
    db.add_all(
        [
            TransportRequestRow(
                id=r.id,
                batch_id=batch.id,
                customer_id=r.customer_id,
                terminal_id=r.terminal_id,
                payload=r.model_dump(mode="json"),
            )
            for r in result.requests
        ]
    )
    db.add_all(
        [
            UnclassifiedRowEntity(id=r.id, batch_id=batch.id, payload=r.model_dump(mode="json"))
            for r in result.unclassified_rows
        ]
    )
    db.commit()


def review_request(db, row: TransportRequestRow, review):
    batch_row = db.get(IngestionBatchRow, row.batch_id)
    result = load_ingestion(db, batch_row)
    request = next(r for r in result.requests if r.id == row.id)
    changes = review.changes.model_dump(exclude_unset=True)
    if changes.get("phone") is not None:
        changes["phone"] = normalize_phone(changes["phone"])
    if "terminal_name" in changes and "terminal_id" not in changes and request.terminal_id:
        terminal = Terminal.model_validate(db.get(TerminalRow, request.terminal_id).payload)
        if changes["terminal_name"] and normalize(changes["terminal_name"]) != normalize(
            terminal.name
        ):
            raise ValueError("Terminal binding must be reviewed explicitly")
    old = {field: getattr(request, field) for field in changes}
    updated = TransportRequest.model_validate(request.model_dump() | changes)
    correction = Correction(
        at=datetime.now(UTC),
        reason=review.reason,
        changes=changes,
        previous_values=old,
        confirmed_fields=review.confirm_fields,
    )
    updated.corrections.append(correction)
    result.requests = [updated if r.id == updated.id else r for r in result.requests]
    validate_requests(result.requests, result.batch.expected_service_date)
    for r in result.requests:
        record = db.get(TransportRequestRow, r.id)
        record.payload = r.model_dump(mode="json")
        record.terminal_id = r.terminal_id
    batch = result.batch
    batch.service_dates = service_dates(result.requests)
    batch.pending_review = sum(
        r.validation_status == ValidationStatus.REVIEW for r in result.requests
    )
    batch.excluded = sum(r.excluded for r in result.requests)
    batch.status = (
        "pending_review"
        if batch.pending_review or any(s.review_required for s in batch.sheets)
        else "interpreted"
    )
    batch_row.payload = batch.model_dump(mode="json")
    for report in db.scalars(
        select(ReconciliationRow).where(
            or_(
                ReconciliationRow.original_batch_id == row.batch_id,
                ReconciliationRow.internal_batch_id == row.batch_id,
            )
        )
    ):
        report.payload = report.payload | {"stale": True}
    db.commit()
    return next(r for r in result.requests if r.id == row.id)
