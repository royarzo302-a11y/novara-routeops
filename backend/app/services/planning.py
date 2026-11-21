from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.excel import validate_passengers
from app.models.entities import DriverRow, OptimizationRow, PassengerRow, ServiceRow, VehicleRow
from app.models.schemas import (
    Driver,
    OptimizationResult,
    Passenger,
    PassengerPatch,
    Service,
    ValidationStatus,
    Vehicle,
)


def available_resources(db: Session, service: ServiceRow):
    vehicles = [Vehicle.model_validate(row.payload) for row in db.scalars(select(VehicleRow))]
    drivers = [Driver.model_validate(row.payload) for row in db.scalars(select(DriverRow))]
    reservations = []
    for row in db.scalars(
        select(OptimizationRow).where(
            OptimizationRow.stale.is_(False),
            OptimizationRow.service_id != service.id,
        )
    ):
        result = OptimizationResult.model_validate(row.payload)
        if result.status == "feasible":
            reservations.extend(result.routes)
    busy = set()
    for driver in drivers:
        start = datetime.combine(service.service_date, driver.available_from)
        end = datetime.combine(service.service_date, driver.available_until)
        if start > end:
            start -= timedelta(days=1)
        for route in reservations:
            if (route.vehicle_id == driver.vehicle_id or route.driver_id == driver.id) and (
                route.service_date == service.service_date
                or (start < route.arrival_at and end > route.departure_at)
            ):
                busy.add(driver.vehicle_id)
    return (
        [v for v in vehicles if v.id not in busy],
        [d for d in drivers if d.vehicle_id not in busy],
        sorted(v.identifier for v in vehicles if v.id in busy),
    )


def service_passengers(db: Session, service_id: str) -> list[Passenger]:
    rows = db.scalars(select(PassengerRow).where(PassengerRow.service_id == service_id)).all()
    return sorted(
        [Passenger.model_validate(row.payload) for row in rows],
        key=lambda p: (p.source_sheet, p.source_row),
    )


def service_schema(db: Session, row: ServiceRow) -> Service:
    return Service(
        id=row.id,
        client=row.client,
        service_date=row.service_date,
        depot_id=row.depot_id,
        status=row.status,
        import_report=row.import_report,
        passenger_ids=[p.id for p in service_passengers(db, row.id)],
    )


def correct_passenger(db: Session, row: PassengerRow, patch: PassengerPatch) -> Passenger:
    service = db.get(ServiceRow, row.service_id)
    changes = patch.model_dump(exclude_unset=True, exclude={"confirm_source_headers"})
    if not changes and not patch.confirm_source_headers:
        raise ValueError("La corrección no contiene cambios")
    if "service_date" in changes and changes["service_date"] != service.service_date:
        raise ValueError("La fecha corregida debe coincidir con la fecha del servicio")
    passengers = service_passengers(db, row.service_id)
    for index, p in enumerate(passengers):
        if p.id != row.id:
            continue
        p = Passenger.model_validate(p.model_dump() | changes)
        p.issues = [
            i
            for i in p.issues
            if i.field not in changes
            and not (patch.confirm_source_headers and i.code == "source_ambiguous_headers")
        ]
        passengers[index] = p
    validate_passengers(passengers)
    for p in passengers:
        db.get(PassengerRow, p.id).payload = p.model_dump(mode="json")
    service.status = (
        "needs_review"
        if any(p.validation_status == ValidationStatus.REVIEW for p in passengers)
        else "imported"
    )
    for plan in db.scalars(
        select(OptimizationRow).where(
            OptimizationRow.service_id == row.service_id,
        )
    ):
        plan.stale = True
    db.commit()
    return next(p for p in passengers if p.id == row.id)
