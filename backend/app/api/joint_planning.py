from datetime import datetime
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request

from app.api.routes import DB, require
from app.geo.models import MatrixRecord, Point
from app.geo.service import GeoInputError, matrix_locations
from app.models.entities import GeoMatrixRow, IngestionBatchRow, TerminalRow, VehicleRow
from app.models.ingestion import DocumentRole, Terminal
from app.models.joint_planning import JointPlan, JointPlanInput, VerifiedPoint
from app.models.preparation import PlanningRules
from app.optimization.joint import Crew, solve_joint
from app.optimization.travel import SubmittedMatrixProvider, TravelMatrix
from app.services.ingestion import load_ingestion
from app.services.planning import available_resources

router = APIRouter(prefix="/v3", tags=["joint-planning"])


@router.post("/plans/preview", response_model=JointPlan)
def preview(body: JointPlanInput, request: Request, db: DB):
    hosted = getattr(request.state, "hosted_session", None)
    if hosted:
        if (
            not body.matrix_id
            or body.request_ids is None
            or len(body.request_ids) > 20
            or len(body.original_batch_ids) > 2
        ):
            raise HTTPException(
                422, "La demo admite dos nóminas, 20 acercamientos y su matriz guardada."
            )
        body = body.model_copy(update=PlanningRules().model_dump())
    requests = []
    for batch_id in body.original_batch_ids:
        batch = load_ingestion(db, require(db, IngestionBatchRow, batch_id))
        if batch.batch.role != DocumentRole.ORIGINAL:
            raise HTTPException(422, "Seleccione lotes originales revisados")
        requests.extend(batch.requests)
    if body.request_ids is not None:
        selected = set(body.request_ids)
        if not selected <= {ride.id for ride in requests}:
            raise HTTPException(422, "Hay solicitudes ajenas a los lotes seleccionados")
        requests = [ride for ride in requests if ride.id in selected]
    if not requests:
        raise HTTPException(422, "Los lotes seleccionados no contienen solicitudes")
    if not body.pickup_points.keys() <= {ride.id for ride in requests}:
        raise HTTPException(422, "Hay recogidas para solicitudes ajenas al plan")
    for vehicle_id in body.vehicle_ids:
        require(db, VehicleRow, vehicle_id)
    # Legacy plans reserve physical resources conservatively for their service date.
    vehicles, drivers, _ = available_resources(
        db,
        SimpleNamespace(id="", service_date=body.service_date),
    )
    drivers_by_vehicle = {driver.vehicle_id: driver for driver in drivers}
    crews = [
        Crew(vehicle, drivers_by_vehicle[vehicle.id])
        for vehicle in vehicles
        if vehicle.id in body.vehicle_ids and vehicle.id in drivers_by_vehicle
    ]
    terminals = {}
    for terminal_id in {ride.terminal_id for ride in requests if ride.terminal_id}:
        row = require(db, TerminalRow, terminal_id)
        terminals[terminal_id] = Terminal.model_validate(row.payload)
    provider = request.app.state.joint_travel_provider
    record = None
    if body.matrix_id:
        body, provider, record = use_cached_matrix(body, request, db, requests)
    if body.matrix:
        data = body.matrix
        provider = SubmittedMatrixProvider(
            data.location_keys,
            TravelMatrix(data.seconds, data.meters, data.source, False),
            data.verified_at,
        )
    if provider is None:
        raise HTTPException(422, "Proporcione una matriz de viaje verificada")
    try:
        plan = solve_joint(
            requests,
            terminals,
            crews,
            body,
            provider,
            allow_simulation=request.app.state.joint_allow_simulation
            or (record is not None and request.app.state.geo_settings.allow_simulation),
        )
        if record and plan.matrix_source:
            plan.matrix_id = record.id
            plan.matrix_mode = record.mode
        elif plan.simulation:
            plan.matrix_mode = "synthetic"
        plan.rules = PlanningRules.model_validate(
            body.model_dump(include=set(PlanningRules.model_fields))
        )
        if hosted:
            hosted.latest_plan = plan.model_dump(mode="json")
        return plan
    except ValueError as exc:
        messages = {
            "Faltan ubicaciones requeridas en la matriz de viaje",
            "La planificación v0.3 requiere una matriz verificada",
            "Máximo 60 solicitudes elegibles por jornada",
        }
        detail = str(exc) if str(exc) in messages else "Datos de planificación o matriz inválidos"
        raise HTTPException(422, detail) from None


def use_cached_matrix(body, request, db, rides):
    settings = request.app.state.geo_settings
    if not settings.token:
        raise HTTPException(503, "Acceso geoespacial deshabilitado")
    row = require(db, GeoMatrixRow, body.matrix_id)
    record = MatrixRecord.model_validate(row.payload["matrix"])
    if record.mode == "time_dependent":
        raise HTTPException(422, "El motor requiere tiempos de viaje estáticos")
    if body.pickup_points:
        raise HTTPException(422, "La matriz guardada usa las recogidas aprobadas")
    request_ids = list(row.payload["approvals"])
    if not set(request_ids) <= {ride.id for ride in rides}:
        raise HTTPException(422, "La matriz contiene solicitudes ajenas al plan")
    origins = {
        key: Point(latitude=p.latitude, longitude=p.longitude)
        for key, p in body.vehicle_origins.items()
    }
    try:
        points, approvals = matrix_locations(db, settings, request_ids, origins)
    except GeoInputError:
        raise HTTPException(409, "Revise las ubicaciones y vuelva a generar la matriz") from None
    if {key: p.model_dump(mode="json") for key, p in points.items()} != row.payload[
        "points"
    ] or approvals != row.payload["approvals"]:
        raise HTTPException(409, "La matriz quedó desactualizada; genere una nueva")
    pickup_points = {
        rid: VerifiedPoint(**points[f"pickup:{rid}"].model_dump(), source="approved_geocoding")
        for rid in request_ids
    }
    provider = SubmittedMatrixProvider(
        record.location_keys,
        TravelMatrix(record.seconds, record.meters, record.provider, record.simulation),
        datetime.fromisoformat(row.payload["verified_at"])
        if row.payload.get("verified_at")
        else None,
    )
    return body.model_copy(update={"pickup_points": pickup_points}), provider, record
