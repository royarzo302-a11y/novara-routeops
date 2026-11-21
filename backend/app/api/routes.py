from datetime import date
from io import BytesIO
from typing import Annotated
from uuid import uuid4
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.export.excel import export_routes
from app.ingestion.excel import parse_excel
from app.models.entities import (
    DepotRow,
    DriverRow,
    OptimizationRow,
    PassengerRow,
    ServiceRow,
    VehicleRow,
)
from app.models.schemas import (
    Depot,
    DepotCreate,
    Driver,
    DriverCreate,
    Issue,
    OptimizationRequest,
    OptimizationResult,
    Passenger,
    PassengerPatch,
    Route,
    Service,
    Vehicle,
    VehicleCreate,
)
from app.optimization.solver import solve
from app.optimization.travel import SyntheticTravelTimeProvider
from app.services.planning import (
    available_resources,
    correct_passenger,
    service_passengers,
    service_schema,
)

router = APIRouter()


def session(request: Request):
    hosted = getattr(request.state, "hosted_session", None)
    factory = hosted.sessions if hosted else request.app.state.sessions
    with request.app.state.database_lock, factory() as db:
        yield db


DB = Annotated[Session, Depends(session)]


def require(db, model, identifier):
    row = db.get(model, identifier)
    if row is None:
        raise HTTPException(404, "Registro no encontrado")
    return row


def save(db, row):
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Identificador o asignación de vehículo ya registrado") from exc


@router.get("/health", tags=["health"])
def health(db: DB):
    db.execute(select(1))
    return {"status": "ok", "mode": "simulation", "version": "0.4.0"}


@router.post("/depots", response_model=Depot, status_code=201, tags=["resources"])
def create_depot(body: DepotCreate, db: DB):
    data = Depot(id=str(uuid4()), **body.model_dump())
    save(db, DepotRow(id=data.id, payload=data.model_dump(mode="json")))
    return data


@router.get("/depots", response_model=list[Depot], tags=["resources"])
def list_depots(db: DB):
    return [row.payload for row in db.scalars(select(DepotRow))]


@router.post("/vehicles", response_model=Vehicle, status_code=201, tags=["resources"])
def create_vehicle(body: VehicleCreate, db: DB):
    data = Vehicle(id=str(uuid4()), **body.model_dump())
    save(
        db, VehicleRow(id=data.id, identifier=data.identifier, payload=data.model_dump(mode="json"))
    )
    return data


@router.get("/vehicles", response_model=list[Vehicle], tags=["resources"])
def list_vehicles(db: DB):
    return [row.payload for row in db.scalars(select(VehicleRow).order_by(VehicleRow.identifier))]


@router.post("/drivers", response_model=Driver, status_code=201, tags=["resources"])
def create_driver(body: DriverCreate, db: DB):
    require(db, VehicleRow, body.vehicle_id)
    data = Driver(id=str(uuid4()), **body.model_dump())
    save(
        db,
        DriverRow(
            id=data.id,
            identifier=data.identifier,
            vehicle_id=data.vehicle_id,
            payload=data.model_dump(mode="json"),
        ),
    )
    return data


@router.get("/drivers", response_model=list[Driver], tags=["resources"])
def list_drivers(db: DB):
    return [row.payload for row in db.scalars(select(DriverRow).order_by(DriverRow.identifier))]


@router.post("/services/import", response_model=Service, status_code=201, tags=["ingestion"])
def import_service(
    file: Annotated[UploadFile, File()],
    service_date: Annotated[date, Form()],
    depot_id: Annotated[str, Form()],
    db: DB,
    client: Annotated[str, Form(min_length=1, max_length=300)] = "Gran América",
):
    require(db, DepotRow, depot_id)
    if not client.strip():
        raise HTTPException(422, "El cliente no puede estar vacío")
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(415, "Solo se admiten archivos .xlsx")
    content = file.file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Máximo 10 MB por archivo")
    identifier = str(uuid4())
    try:
        passengers, report = parse_excel(content, identifier, service_date)
    except (
        ValueError,
        TypeError,
        BadZipFile,
        InvalidFileException,
        ParseError,
        KeyError,
        OSError,
    ) as exc:
        raise HTTPException(422, f"No fue posible importar: {exc}") from exc
    service = ServiceRow(
        id=identifier,
        client=client.strip(),
        service_date=service_date,
        depot_id=depot_id,
        status="needs_review" if report["pending_review"] else "imported",
        import_report=report,
    )
    db.add(service)
    db.flush()
    db.add_all(
        [
            PassengerRow(id=p.id, service_id=identifier, payload=p.model_dump(mode="json"))
            for p in passengers
        ]
    )
    db.commit()
    return service_schema(db, service)


@router.get("/services", response_model=list[Service], tags=["services"])
def list_services(db: DB):
    return [service_schema(db, row) for row in db.scalars(select(ServiceRow))]


@router.get("/services/{service_id}", response_model=Service, tags=["services"])
def get_service(service_id: str, db: DB):
    return service_schema(db, require(db, ServiceRow, service_id))


@router.get("/services/{service_id}/passengers", response_model=list[Passenger], tags=["ingestion"])
def get_passengers(service_id: str, db: DB):
    require(db, ServiceRow, service_id)
    return service_passengers(db, service_id)


@router.get("/services/{service_id}/validation-errors", tags=["ingestion"])
def get_errors(service_id: str, db: DB):
    require(db, ServiceRow, service_id)
    return [
        {"passenger_id": p.id, "status": p.validation_status, "issues": p.issues}
        for p in service_passengers(db, service_id)
        if p.issues
    ]


@router.patch("/passengers/{passenger_id}", response_model=Passenger, tags=["ingestion"])
def patch_passenger(passenger_id: str, body: PassengerPatch, db: DB):
    row = require(db, PassengerRow, passenger_id)
    try:
        return correct_passenger(db, row, body)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post(
    "/services/{service_id}/optimize",
    response_model=OptimizationResult,
    status_code=201,
    tags=["planning"],
)
def optimize(service_id: str, body: OptimizationRequest, db: DB):
    service = require(db, ServiceRow, service_id)
    depot = Depot.model_validate(require(db, DepotRow, service.depot_id).payload)
    vehicles, drivers, reserved = available_resources(db, service)
    try:
        result = solve(
            service_id,
            [p for p in service_passengers(db, service_id) if not p.excluded],
            vehicles,
            drivers,
            depot,
            body,
            SyntheticTravelTimeProvider(),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # A new plan supersedes previous ones, including after an infeasible attempt.
    if reserved:
        result.diagnostics.append(
            Issue(
                code="reserved_resources",
                severity="warning",
                message="Vans reservadas por otros servicios vigentes: " + ", ".join(reserved),
            )
        )
    for row in db.scalars(select(OptimizationRow).where(OptimizationRow.service_id == service_id)):
        row.stale = True
    db.add(
        OptimizationRow(id=result.id, service_id=service_id, payload=result.model_dump(mode="json"))
    )
    service.status = "planned" if result.status == "feasible" else result.status
    db.commit()
    return result


@router.get(
    "/services/{service_id}/optimizations",
    response_model=list[OptimizationResult],
    tags=["planning"],
)
def list_results(service_id: str, db: DB):
    require(db, ServiceRow, service_id)
    return [
        OptimizationResult.model_validate(row.payload).model_copy(update={"stale": row.stale})
        for row in db.scalars(
            select(OptimizationRow).where(
                OptimizationRow.service_id == service_id,
            )
        )
    ]


def current_result(db, optimization_id):
    row = require(db, OptimizationRow, optimization_id)
    return OptimizationResult.model_validate(row.payload).model_copy(update={"stale": row.stale})


@router.get(
    "/optimizations/{optimization_id}", response_model=OptimizationResult, tags=["planning"]
)
def get_result(optimization_id: str, db: DB):
    return current_result(db, optimization_id)


@router.get(
    "/optimizations/{optimization_id}/routes", response_model=list[Route], tags=["planning"]
)
def get_routes(optimization_id: str, db: DB):
    return current_result(db, optimization_id).routes


@router.get(
    "/optimizations/{optimization_id}/export",
    tags=["export"],
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
            }
        }
    },
)
def export(optimization_id: str, db: DB):
    try:
        content = export_routes(current_result(db, optimization_id))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="simulation-{optimization_id}.xlsx"'
        },
    )
