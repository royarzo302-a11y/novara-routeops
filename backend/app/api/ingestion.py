from datetime import date
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select

from app.api.routes import DB, require
from app.ingestion.real_excel import IngestionError, parse_real_excel
from app.models.entities import (
    CustomerRow,
    IngestionBatchRow,
    ReconciliationRow,
    TerminalRow,
    TransportRequestRow,
)
from app.models.ingestion import (
    Customer,
    CustomerCode,
    DocumentRole,
    IngestionBatch,
    IngestionResult,
    ReconcileInput,
    ReconciliationReport,
    ReviewRequest,
    Terminal,
    TerminalCreate,
    TransportRequest,
)
from app.services.ingestion import load_ingestion, persist_ingestion, review_request
from app.services.reconciliation import reconcile

router = APIRouter(prefix="/v2", tags=["ingestion-v0.2"])


@router.get("/customers", response_model=list[Customer])
def customers(db: DB):
    return list(db.scalars(select(CustomerRow).order_by(CustomerRow.id)))


@router.post("/terminals", response_model=Terminal, status_code=201)
def create_terminal(body: TerminalCreate, db: DB):
    require(db, CustomerRow, body.customer_id)
    data = Terminal(id=str(uuid4()), **body.model_dump())
    db.add(
        TerminalRow(id=data.id, customer_id=data.customer_id, payload=data.model_dump(mode="json"))
    )
    db.commit()
    return data


@router.get("/terminals", response_model=list[Terminal])
def terminals(db: DB, customer_id: CustomerCode | None = None):
    query = select(TerminalRow)
    if customer_id:
        query = query.where(TerminalRow.customer_id == customer_id)
    return [row.payload for row in db.scalars(query)]


def get_terminal(db, terminal_id, customer_id):
    if terminal_id is None:
        return None
    terminal = Terminal.model_validate(require(db, TerminalRow, terminal_id).payload)
    if terminal.customer_id != customer_id:
        raise HTTPException(422, "El terminal pertenece a otro cliente")
    return terminal


def read_xlsx(file: UploadFile) -> bytes:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(415, "Solo se admiten libros .xlsx")
    content = file.file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Máximo 10 MB por archivo")
    return content


@router.post("/ingestions", response_model=IngestionResult, status_code=201)
def ingest(
    file: Annotated[UploadFile, File()],
    customer_id: Annotated[CustomerCode, Form()],
    role: Annotated[DocumentRole, Form()],
    db: DB,
    archive_date: Annotated[date | None, Form()] = None,
    expected_service_date: Annotated[date | None, Form()] = None,
    terminal_id: Annotated[str | None, Form()] = None,
):
    content = read_xlsx(file)
    terminal = get_terminal(db, terminal_id, customer_id)
    try:
        result = parse_real_excel(
            content,
            customer_id,
            role,
            archive_date=archive_date,
            expected_service_date=expected_service_date,
            terminal=terminal,
        )
    except IngestionError as exc:
        raise HTTPException(422, str(exc)) from None
    persist_ingestion(db, result)
    return result


@router.get("/ingestions", response_model=list[IngestionBatch])
def batches(db: DB):
    records = [
        IngestionBatch.model_validate(row.payload) for row in db.scalars(select(IngestionBatchRow))
    ]
    previous = {
        record.id: record for record in records if "service_dates" not in record.model_fields_set
    }
    if previous:
        payload = TransportRequestRow.payload
        service_date = payload["service_date"].as_string()
        dates = db.execute(
            select(TransportRequestRow.batch_id, service_date)
            .where(
                TransportRequestRow.batch_id.in_(previous),
                service_date.is_not(None),
                payload["direction"].as_string() == "inbound",
                payload["excluded"].as_boolean().is_(False),
            )
            .distinct()
            .order_by(service_date)
        )
        for batch_id, value in dates:
            previous[batch_id].service_dates.append(date.fromisoformat(value))
    return sorted(records, key=lambda record: record.created_at, reverse=True)


@router.get("/ingestions/{batch_id}", response_model=IngestionResult)
def ingestion(batch_id: str, db: DB):
    return load_ingestion(db, require(db, IngestionBatchRow, batch_id))


@router.get("/ingestions/{batch_id}/summary")
def summary(batch_id: str, db: DB):
    # This endpoint is safe for aggregate reporting: no cells, names, codes or contact details.
    return require(db, IngestionBatchRow, batch_id).payload


@router.get("/requests/{request_id}", response_model=TransportRequest)
def request_details(request_id: str, db: DB):
    return require(db, TransportRequestRow, request_id).payload


@router.patch("/requests/{request_id}", response_model=TransportRequest)
def review(request_id: str, body: ReviewRequest, request: Request, db: DB):
    row = require(db, TransportRequestRow, request_id)
    hosted = getattr(request.state, "hosted_session", None)
    if hosted:
        expected = hosted.valid_communes.get(row.payload.get("address"))
        changes = body.changes.model_dump(exclude_unset=True)
        if changes != {"commune": expected} or not expected or body.confirm_fields:
            raise HTTPException(422, "Solo puedes corregir la comuna del punto público de ejemplo.")
        body = body.model_copy(update={"reason": "Corrección de comuna en la demo"})
    if "terminal_id" in body.changes.model_fields_set:
        get_terminal(db, body.changes.terminal_id, row.customer_id)
    try:
        result = review_request(db, row, body)
        if hosted:
            hosted.latest_plan = None
        return result
    except ValueError:
        raise HTTPException(422, "La corrección contiene un valor no válido") from None


@router.post("/reconciliations", response_model=ReconciliationReport, status_code=201)
def create_reconciliation(body: ReconcileInput, db: DB):
    original = load_ingestion(db, require(db, IngestionBatchRow, body.original_batch_id))
    internal = load_ingestion(db, require(db, IngestionBatchRow, body.internal_batch_id))
    try:
        result = reconcile(original, internal)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    db.add(
        ReconciliationRow(
            id=result.id,
            original_batch_id=result.original_batch_id,
            internal_batch_id=result.internal_batch_id,
            payload=result.model_dump(mode="json"),
        )
    )
    db.commit()
    return result


@router.get("/reconciliations/{report_id}", response_model=ReconciliationReport)
def reconciliation(report_id: str, db: DB):
    return require(db, ReconciliationRow, report_id).payload
