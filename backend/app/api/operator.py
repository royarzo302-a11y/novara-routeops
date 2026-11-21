"""Protected operator actions used by the local dashboard."""

import hashlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Body, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import select

from app.api.geospatial import GeoAccess
from app.api.ingestion import read_xlsx
from app.api.routes import DB, require
from app.export.excel import export_joint_preview
from app.geo.models import Approval, LocationReview, MatrixInput, MatrixRecord
from app.geo.service import (
    GeoInputError,
    address_key,
    approve,
    get_request,
    location_review,
    lookup,
    matrix_locations,
    request_address,
    save_review,
)
from app.ingestion.real_excel import (
    IngestionError,
    detect_original_customer,
    employee_identity,
    parse_real_excel,
)
from app.models.entities import (
    CustomerRow,
    DepotRow,
    DriverRow,
    GeoMatrixRow,
    LocationReviewRow,
    OperationSettingsRow,
    TerminalRow,
    TransportRequestRow,
    VehicleRow,
)
from app.models.ingestion import DocumentRole, IngestionResult, Terminal, TransportRequest
from app.models.joint_planning import JointPlan, VerifiedMatrixInput
from app.models.preparation import Preparation, PreparationView
from app.models.schemas import Driver, DriverCreate, Vehicle, VehicleCreate
from app.services.ingestion import persist_ingestion
from app.services.preparation import load_preparation

router = APIRouter(prefix="/v5/operator", tags=["operator"])


class RoadMatrixImport(MatrixInput):
    matrix: VerifiedMatrixInput


@router.post("/matrices/import", response_model=MatrixRecord, status_code=201)
def import_road_matrix(body: RoadMatrixImport, db: DB, access: GeoAccess):
    if access.demo_mode:
        raise HTTPException(403, "La red vial de la demo está fija.")
    if body.departure_at:
        raise HTTPException(422, "Importe una matriz de tiempos estáticos")
    try:
        points, approvals = matrix_locations(db, access, body.request_ids, body.vehicle_origins)
    except GeoInputError as exc:
        raise HTTPException(422, str(exc)) from None
    if set(body.matrix.location_keys) != set(points):
        raise HTTPException(
            422, "La matriz debe incluir las recogidas, terminales y orígenes actuales"
        )
    matrix = MatrixRecord(
        id=str(uuid4()),
        provider=body.matrix.source,
        profile="submitted",
        mode="static_road",
        map_version=body.matrix.verified_at.isoformat(),
        generated_at=datetime.now(UTC),
        departure_at=None,
        simulation=False,
        location_keys=body.matrix.location_keys,
        seconds=body.matrix.seconds,
        meters=body.matrix.meters,
        unreachable_pairs=0,
        isolated_location_keys=[],
    )
    db.add(
        GeoMatrixRow(
            id=matrix.id,
            cache_key="submitted:" + matrix.id,
            payload={
                "matrix": matrix.model_dump(mode="json"),
                "verified_at": body.matrix.verified_at.isoformat(),
                "points": {key: point.model_dump(mode="json") for key, point in points.items()},
                "approvals": approvals,
            },
        )
    )
    db.commit()
    return matrix


@router.get("/preparation", response_model=PreparationView)
def preparation(db: DB, access: GeoAccess):
    return PreparationView(
        **load_preparation(db, demo=access.demo_mode).model_dump(), locked=access.demo_mode
    )


@router.put("/preparation", response_model=PreparationView)
def save_preparation(body: Preparation, db: DB, access: GeoAccess):
    if access.demo_mode:
        raise HTTPException(403, "Los factores de la demo están fijos para comparar nóminas.")
    if body.depot_id:
        require(db, DepotRow, body.depot_id)
    for customer_id, terminal_id in body.terminal_ids.items():
        terminal = require(db, TerminalRow, terminal_id)
        if terminal.customer_id != customer_id:
            raise HTTPException(422, "El terminal pertenece a otro cliente")
        if any(terminal.payload.get(axis) is None for axis in ("latitude", "longitude")):
            raise HTTPException(422, "El terminal necesita coordenadas")
    if body.matrix_id:
        matrix = require(db, GeoMatrixRow, body.matrix_id).payload["matrix"]
        if matrix["mode"] != "static_road" or matrix["simulation"]:
            raise HTTPException(422, "Seleccione una matriz vial estática verificada")
    row = db.get(OperationSettingsRow, "preparation")
    if row is None:
        row = OperationSettingsRow(id="preparation", payload={})
        db.add(row)
    row.payload = body.model_dump(mode="json")
    db.commit()
    return PreparationView(**body.model_dump())


@router.post("/ingestions/automatic", response_model=IngestionResult, status_code=201)
def automatic_ingestion(
    file: Annotated[UploadFile, File()], request: Request, db: DB, access: GeoAccess
):
    content = read_xlsx(file)
    hosted = getattr(request.state, "hosted_session", None)
    if hosted and hashlib.sha256(content).hexdigest() not in hosted.rosters:
        raise HTTPException(422, "Carga un Excel de ejemplo descargado desde esta sesión.")
    if hosted and hosted.uploads >= 12:
        raise HTTPException(429, "Restablece la demo para importar más nóminas.")
    try:
        customer = detect_original_customer(content, file.filename or "")
        terminals = list(db.scalars(select(TerminalRow).where(TerminalRow.customer_id == customer)))
        config = load_preparation(db, demo=access.demo_mode)
        selected = config.terminal_ids.get(customer)
        row = next((row for row in terminals if row.id == selected), None)
        if row is None and len(terminals) == 1:
            row = terminals[0]
        terminal = Terminal.model_validate(row.payload) if row else None
        result = parse_real_excel(content, customer, DocumentRole.ORIGINAL, terminal=terminal)
    except IngestionError as exc:
        raise HTTPException(422, str(exc)) from None
    if not result.requests:
        raise HTTPException(422, "El Excel no contiene solicitudes activas reconocidas.")
    if access.demo_mode and any(
        not (ride.employee_code or "").startswith("NOVARA-DEMO-") for ride in result.requests
    ):
        raise HTTPException(422, "La demo solo admite la nómina ficticia suministrada.")
    persist_ingestion(db, result)
    if hosted:
        hosted.uploads += 1
        hosted.latest_plan = None
    return result


@router.post("/locations/prepare", response_model=dict[str, LocationReview])
def prepare_locations(ids: Annotated[list[str], Body(max_length=60)], db: DB, access: GeoAccess):
    try:
        rides = [get_request(db, rid) for rid in dict.fromkeys(ids)]
    except GeoInputError as exc:
        raise HTTPException(422, str(exc)) from None
    output = {}
    for ride in rides:
        current = location_review(db, access, ride)
        check = request_address(ride, "Santiago")
        if current.status != "approved" and check and not check.issues:
            if access.demo_mode and (ride.employee_code or "").startswith("NOVARA-DEMO-"):
                current = lookup(db, access, ride, "Santiago")
                candidates = [point for point in current.candidates if point.context_match]
                if len(candidates) == 1:
                    current = approve(
                        db,
                        access,
                        ride,
                        Approval(
                            candidate_id=candidates[0].id,
                            reason="Coordenada del ejemplo de simulación",
                        ),
                    )
            elif not access.demo_mode and employee_identity(ride.employee_code):
                key = address_key(access, check)
                query = (
                    select(TransportRequestRow)
                    .join(LocationReviewRow, LocationReviewRow.id == TransportRequestRow.id)
                    .where(
                        TransportRequestRow.customer_id == ride.customer_id,
                        TransportRequestRow.id != ride.id,
                        LocationReviewRow.payload["address_key"].as_string() == key,
                    )
                )
                sources = [
                    location_review(db, access, other, "Santiago")
                    for row in db.scalars(query)
                    if employee_identity(
                        (other := TransportRequest.model_validate(row.payload)).employee_code
                    )
                    == employee_identity(ride.employee_code)
                ]
                approved = [
                    item for item in sources if item.status == "approved" and item.approved_point
                ]
                if approved and all(
                    item.approved_point == approved[0].approved_point for item in approved
                ):
                    current = save_review(
                        db,
                        access,
                        current.model_copy(
                            update={
                                "address": check,
                                "status": "approved",
                                "approved_point": approved[0].approved_point,
                                "approval_source": approved[0].approval_source,
                                "approval_reason": "Mismo código y domicilio aprobado",
                            }
                        ),
                    )
        output[ride.id] = current
    return output


@router.put("/vehicles/{vehicle_id}", response_model=Vehicle)
def update_vehicle(vehicle_id: str, body: VehicleCreate, db: DB, access: GeoAccess):
    row = require(db, VehicleRow, vehicle_id)
    if body.identifier != row.identifier:
        raise HTTPException(422, "El identificador de una van registrada se conserva")
    vehicle = Vehicle(id=row.id, **body.model_dump())
    row.payload = vehicle.model_dump(mode="json")
    db.commit()
    return vehicle


@router.put("/drivers/{driver_id}", response_model=Driver)
def update_driver(driver_id: str, body: DriverCreate, db: DB, access: GeoAccess):
    row = require(db, DriverRow, driver_id)
    if body.vehicle_id != row.vehicle_id or body.identifier != row.identifier:
        raise HTTPException(422, "La asignación e identidad del conductor se conservan")
    driver = Driver(id=row.id, **body.model_dump())
    row.payload = driver.model_dump(mode="json")
    db.commit()
    return driver


@router.post("/plans/export")
def download(body: JointPlan, request: Request, access: GeoAccess, db: DB):
    hosted = getattr(request.state, "hosted_session", None)
    if hosted and body.model_dump(mode="json") != hosted.latest_plan:
        raise HTTPException(409, "Recalcula la jornada antes de descargar el Excel.")
    if not body.trips or len(body.trips) > 6 or sum(len(t.stops) for t in body.trips) > 60:
        raise HTTPException(422, "La vista previa no contiene viajes exportables")
    if len(body.unassigned) > 10000:
        raise HTTPException(422, "La lista de solicitudes sin asignar supera el límite")

    def records(model, ids):
        return {row.id: row.payload for row in db.scalars(select(model).where(model.id.in_(ids)))}

    requests = {stop.request_id for trip in body.trips for stop in trip.stops}
    requests.update(row.request_id for row in body.unassigned)
    customers = {row.id: row.name for row in db.scalars(select(CustomerRow))}
    return Response(
        export_joint_preview(
            body,
            requests=records(TransportRequestRow, requests),
            vehicles=records(VehicleRow, {trip.vehicle_id for trip in body.trips}),
            drivers=records(DriverRow, {trip.driver_id for trip in body.trips}),
            terminals=records(TerminalRow, {trip.terminal_id for trip in body.trips}),
            customers=customers,
        ),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="novara-vista-previa.xlsx"',
            "Cache-Control": "no-store",
        },
    )
