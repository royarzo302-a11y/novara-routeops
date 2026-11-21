import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.api.routes import DB, require
from app.geo.models import (
    AddressCheck,
    AddressInput,
    Approval,
    GeocodeQuery,
    LocationReview,
    MatrixInput,
    MatrixMetadata,
    MatrixRecord,
    Point,
)
from app.geo.providers import GeoProviderError, check_address
from app.geo.service import (
    GeoInputError,
    approve,
    create_matrix,
    get_request,
    location_review,
    lookup,
)
from app.models.entities import DepotRow, GeoMatrixRow

router = APIRouter(prefix="/v4/geo", tags=["geospatial"])
bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def geo_access(request: Request, credentials: Credentials):
    settings = request.app.state.geo_settings
    if not settings.token:
        raise HTTPException(503, "Acceso geoespacial deshabilitado")
    if credentials is None or not hmac.compare_digest(
        credentials.credentials.encode(),
        settings.token.encode(),
    ):
        raise HTTPException(401, "Autorización requerida", headers={"WWW-Authenticate": "Bearer"})
    return settings


GeoAccess = Annotated[object, Depends(geo_access)]


@router.post("/addresses/validate", response_model=AddressCheck)
def validate_address(body: AddressInput, access: GeoAccess):
    return check_address(body.address, body.commune, body.city)


@router.get("/requests/{request_id}/location", response_model=LocationReview)
def review_status(request_id: str, db: DB, access: GeoAccess):
    try:
        return location_review(db, access, get_request(db, request_id))
    except GeoInputError as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/requests/{request_id}/candidates", response_model=LocationReview)
def candidates(request_id: str, body: GeocodeQuery, db: DB, access: GeoAccess):
    try:
        return lookup(db, access, get_request(db, request_id), body.city)
    except GeoInputError as exc:
        raise HTTPException(422, str(exc)) from None
    except GeoProviderError:
        raise HTTPException(502, "Búsqueda cartográfica no disponible") from None


@router.put("/requests/{request_id}/location", response_model=LocationReview)
def approve_location(request_id: str, body: Approval, db: DB, access: GeoAccess):
    try:
        return approve(db, access, get_request(db, request_id), body)
    except GeoInputError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/matrices", response_model=MatrixMetadata, status_code=201)
def build_matrix(body: MatrixInput, request: Request, db: DB, access: GeoAccess):
    hosted = getattr(request.state, "hosted_session", None)
    if hosted:
        base = require(db, DepotRow, "base-demo").payload
        if len(body.request_ids) > 20 or any(
            (p.latitude, p.longitude) != (base["latitude"], base["longitude"])
            for p in body.vehicle_origins.values()
        ):
            raise HTTPException(422, "La demo admite 20 recogidas y la base de salida incluida.")
        if hosted.matrices >= 20:
            raise HTTPException(429, "Restablece la demo para generar más matrices.")
    try:
        result = create_matrix(db, access, body)
        if hosted:
            hosted.matrices += 1
            hosted.latest_plan = None
        return result
    except GeoInputError as exc:
        raise HTTPException(422, str(exc)) from None
    except ValueError:
        raise HTTPException(502, "Matriz cartográfica inválida o no disponible") from None


@router.get("/matrices/{matrix_id}", response_model=MatrixRecord)
def get_matrix(matrix_id: str, db: DB, access: GeoAccess):
    return require(db, GeoMatrixRow, matrix_id).payload["matrix"]


@router.get("/matrices/{matrix_id}/metadata", response_model=MatrixMetadata)
def get_metadata(matrix_id: str, db: DB, access: GeoAccess):
    return MatrixRecord.model_validate(require(db, GeoMatrixRow, matrix_id).payload["matrix"])


@router.get("/session")
def operator_session(access: GeoAccess):
    return {
        "authenticated": True,
        "demo": access.demo_mode,
        "geocoder_available": bool(access.geocoder),
        "road_available": bool(access.road),
    }


@router.get("/matrix-catalog", response_model=list[MatrixMetadata])
def matrix_catalog(db: DB, access: GeoAccess):
    records = [
        MatrixRecord.model_validate(row.payload["matrix"])
        for row in db.scalars(select(GeoMatrixRow))
    ]
    return sorted(records, key=lambda record: record.generated_at, reverse=True)


@router.get("/matrices/{matrix_id}/origins", response_model=dict[str, Point])
def matrix_origins(matrix_id: str, db: DB, access: GeoAccess):
    row = require(db, GeoMatrixRow, matrix_id)
    return {
        key.removeprefix("origin:"): point
        for key, point in row.payload["points"].items()
        if key.startswith("origin:")
    }
