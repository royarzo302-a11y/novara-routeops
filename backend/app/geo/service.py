import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.geo.models import LocationReview, MatrixRecord, Point
from app.geo.providers import (
    GeocodingProvider,
    NominatimProvider,
    OSRMProvider,
    RoadMatrixProvider,
    check_address,
)
from app.models.entities import (
    GeocodeCacheRow,
    GeoMatrixRow,
    LocationReviewRow,
    TerminalRow,
    TransportRequestRow,
    VehicleRow,
)
from app.models.ingestion import Terminal, TransportRequest
from app.optimization.travel import Location


@dataclass(frozen=True)
class GeoSettings:
    token: str = ""
    geocoder: GeocodingProvider | None = None
    road: RoadMatrixProvider | None = None
    allow_simulation: bool = False
    demo_mode: bool = False
    # Approximate coverage bounds, not commune boundaries.
    bounds: tuple[float, float, float, float] = (-34.25, -33.0, -71.8, -69.75)

    @classmethod
    def from_env(cls):
        token = os.getenv("NOVARA_GEO_TOKEN", "")
        if os.getenv("NOVARA_GEO_LOCAL_AUTHORIZED", "") != "1":
            return cls(token=token)
        nominatim = os.getenv("NOVARA_NOMINATIM_URL")
        osrm = os.getenv("NOVARA_OSRM_URL")
        version = os.getenv("NOVARA_GEO_MAP_VERSION", "").strip()
        if (nominatim or osrm) and (not version or not token):
            raise ValueError(
                "Configure token y versión de mapas para habilitar proveedores locales"
            )
        return cls(
            token=token,
            geocoder=NominatimProvider(nominatim, version) if nominatim else None,
            road=OSRMProvider(osrm, version, os.getenv("NOVARA_OSRM_PROFILE", "driving"))
            if osrm
            else None,
        )

    def key(self, *parts):
        data = json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()
        return hmac.new(self.token.encode(), data, hashlib.sha256).hexdigest()

    def in_bounds(self, point):
        a, b, c, d = self.bounds
        return a <= point.latitude <= b and c <= point.longitude <= d


class GeoInputError(ValueError):
    pass


def get_request(db, request_id):
    row = db.get(TransportRequestRow, request_id)
    if row is None:
        raise GeoInputError("Solicitud inexistente")
    return TransportRequest.model_validate(row.payload)


def request_address(ride, city):
    if not ride.address or not ride.commune:
        return None
    return check_address(ride.address, ride.commune, city)


def address_key(settings, check):
    if check is None:
        return None
    return settings.key(check.normalized_address, check.normalized_commune, check.normalized_city)


def location_review(db, settings, ride, city=None):
    row = db.get(LocationReviewRow, ride.id)
    previous = LocationReview.model_validate(row.payload["review"]) if row else None
    city = city or (previous.address.city if previous and previous.address else "Santiago")
    check = request_address(ride, city)
    key = address_key(settings, check)
    if row and key and hmac.compare_digest(key, row.payload["address_key"] or ""):
        return previous.model_copy(update={"address": check})
    return LocationReview(
        request_id=ride.id, address=check, status="pending", updated_at=datetime.now(UTC)
    )


def save_review(db, settings, review):
    payload = {
        "address_key": address_key(settings, review.address),
        "review": review.model_dump(mode="json"),
    }
    row = db.get(LocationReviewRow, review.request_id)
    if row is None:
        db.add(LocationReviewRow(id=review.request_id, payload=payload))
    else:
        row.payload = payload
    db.commit()
    return review


def lookup(db, settings, ride, city):
    review = location_review(db, settings, ride, city)
    if review.status == "approved":
        return review
    address = review.address
    if not address or address.issues or not settings.geocoder:
        return save_review(db, settings, review)
    provider = settings.geocoder
    if provider.name == "synthetic_geocoding" and not settings.allow_simulation:
        raise GeoInputError("El geocodificador de prueba está deshabilitado")
    key = settings.key(
        "geocode-v1",
        address_key(settings, address),
        provider.name,
        provider.cache_scope,
        provider.version,
    )
    cached = db.get(GeocodeCacheRow, key)
    if cached is None:
        candidates = [
            candidate.model_dump(mode="json")
            for candidate in provider.candidates(address)
            if settings.in_bounds(candidate)
        ]
        now = datetime.now(UTC)
        payload = {
            "candidates": candidates,
            "updated_at": now.isoformat(),
            "provider": provider.name,
            "map_version": provider.version,
        }
        db.add(GeocodeCacheRow(id=key, payload=payload))
    else:
        payload = cached.payload
    updated = LocationReview.model_validate(
        review.model_dump()
        | {
            "status": "review_required",
            "candidates": payload["candidates"],
            "provider": provider.name,
            "map_version": provider.version,
            "updated_at": datetime.now(UTC),
        }
    )
    return save_review(db, settings, updated)


def approve(db, settings, ride, body):
    review = location_review(db, settings, ride)
    if not review.address:
        raise GeoInputError("Complete la dirección y comuna en la solicitud")
    point = body.point
    source = "manual"
    if body.candidate_id:
        candidate = next((c for c in review.candidates if c.id == body.candidate_id), None)
        if candidate is None or not candidate.context_match:
            raise GeoInputError("Seleccione un candidato compatible o corrija el punto manualmente")
        point = Point(latitude=candidate.latitude, longitude=candidate.longitude)
        source = review.provider
    if not settings.in_bounds(point):
        raise GeoInputError("El punto está fuera de la cobertura configurada")
    return save_review(
        db,
        settings,
        review.model_copy(
            update={
                "status": "approved",
                "approved_point": point,
                "approval_source": source,
                "approval_reason": body.reason,
                "updated_at": datetime.now(UTC),
            }
        ),
    )


def matrix_locations(db, settings, request_ids, vehicle_origins):
    points, approvals = {}, {}
    terminal_ids = set()
    for request_id in sorted(request_ids):
        ride = get_request(db, request_id)
        review = location_review(db, settings, ride)
        if review.status != "approved" or not review.approved_point:
            raise GeoInputError("Hay recogidas sin coordenadas aprobadas")
        points[f"pickup:{request_id}"] = review.approved_point
        approvals[request_id] = review.updated_at.isoformat()
        row = db.get(TerminalRow, ride.terminal_id) if ride.terminal_id else None
        if row is None:
            raise GeoInputError("Hay solicitudes sin terminal asociado")
        terminal = Terminal.model_validate(row.payload)
        if terminal.customer_id != ride.customer_id or terminal.latitude is None:
            raise GeoInputError("Hay terminales sin coordenadas o fuera del cliente")
        terminal_ids.add(terminal.id)
    for terminal_id in sorted(terminal_ids):
        terminal = Terminal.model_validate(db.get(TerminalRow, terminal_id).payload)
        points[f"terminal:{terminal_id}"] = Point(
            latitude=terminal.latitude,
            longitude=terminal.longitude,
        )
    for vehicle_id, point in sorted(vehicle_origins.items()):
        if db.get(VehicleRow, vehicle_id) is None:
            raise GeoInputError("Hay vehículos sin registrar")
        points[f"origin:{vehicle_id}"] = point
    if not all(settings.in_bounds(point) for point in points.values()):
        raise GeoInputError("Hay coordenadas fuera de la cobertura configurada")
    return points, approvals


def create_matrix(db, settings, body):
    provider = settings.road
    if not provider:
        raise GeoInputError("Configure un proveedor vial local autorizado")
    if provider.mode == "synthetic" and not settings.allow_simulation:
        raise GeoInputError("El proveedor sintético está deshabilitado")
    if body.departure_at and provider.mode != "time_dependent":
        raise GeoInputError("El proveedor no admite estimaciones por hora de salida")
    if provider.mode == "time_dependent" and not body.departure_at:
        raise GeoInputError("Indique la hora de salida para la estimación temporal")
    points, approvals = matrix_locations(db, settings, body.request_ids, body.vehicle_origins)
    snapshot = {key: point.model_dump(mode="json") for key, point in points.items()}
    departure = body.departure_at.astimezone(UTC) if body.departure_at else None
    key = settings.key(
        "matrix-v1",
        provider.name,
        provider.cache_scope,
        provider.version,
        provider.profile,
        provider.mode,
        "seconds",
        "meters",
        departure.isoformat() if departure else None,
        snapshot,
        approvals,
    )
    cached = db.scalar(select(GeoMatrixRow).where(GeoMatrixRow.cache_key == key))
    if cached:
        return MatrixRecord.model_validate(cached.payload["matrix"])
    result = provider.matrix(
        [Location(p.latitude, p.longitude) for p in points.values()],
        departure_at=departure,
    )
    result.validate(len(points), allow_unreachable=True)
    if result.simulation != (provider.mode == "synthetic"):
        raise GeoInputError("La procedencia de simulación no coincide con el proveedor")
    keys = list(points)
    matrix = MatrixRecord(
        id=str(uuid4()),
        provider=provider.name,
        profile=provider.profile,
        mode=provider.mode,
        map_version=provider.version,
        upstream_data_version=result.data_version,
        generated_at=datetime.now(UTC),
        departure_at=departure,
        simulation=result.simulation,
        location_keys=keys,
        seconds=result.seconds,
        meters=result.meters,
        unreachable_pairs=sum(row.count(None) for row in result.seconds),
        isolated_location_keys=[
            key
            for i, key in enumerate(keys)
            if len(keys) > 1
            and all(
                result.seconds[i][j] is None and result.seconds[j][i] is None
                for j in range(len(keys))
                if i != j
            )
        ],
    )
    db.add(
        GeoMatrixRow(
            id=matrix.id,
            cache_key=key,
            payload={
                "matrix": matrix.model_dump(mode="json"),
                "points": snapshot,
                "approvals": approvals,
            },
        )
    )
    db.commit()
    return matrix
