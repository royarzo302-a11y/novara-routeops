from datetime import date, datetime
from typing import Literal

from pydantic import Field, StrictInt, model_validator

from app.models.ingestion import CustomerCode
from app.models.preparation import PlanningRules
from app.models.schemas import Latitude, Longitude, Schema, Text


class VerifiedPoint(Schema):
    latitude: Latitude
    longitude: Longitude
    source: Text


class VerifiedMatrixInput(Schema):
    source: Text
    verified_at: datetime
    location_keys: list[str] = Field(min_length=1, max_length=123)
    seconds: list[list[StrictInt]] = Field(max_length=123)
    meters: list[list[StrictInt]] = Field(max_length=123)

    @model_validator(mode="after")
    def validate_matrix(self):
        from app.optimization.travel import TravelMatrix

        if self.verified_at.utcoffset() is None:
            raise ValueError("Indique la zona horaria de la verificación")
        if len(set(self.location_keys)) != len(self.location_keys):
            raise ValueError("Las claves de la matriz deben ser únicas")
        TravelMatrix(self.seconds, self.meters, self.source, False).validate(
            len(self.location_keys)
        )
        return self


class JointPlanInput(Schema):
    service_date: date
    original_batch_ids: list[str] = Field(min_length=1, max_length=30)
    request_ids: list[str] | None = Field(default=None, min_length=1, max_length=60)
    vehicle_ids: list[str] = Field(min_length=3, max_length=3)
    vehicle_origins: dict[str, VerifiedPoint]
    pickup_points: dict[str, VerifiedPoint] = Field(default_factory=dict)
    matrix_id: str | None = None
    matrix: VerifiedMatrixInput | None = None
    preparation_seconds: int = Field(default=600, ge=0, le=7200)
    boarding_seconds: int = Field(default=60, ge=0, le=600)
    arrival_buffer_minutes: int = Field(default=10, ge=0, le=120)
    max_early_arrival_minutes: int = Field(default=30, ge=0, le=180)
    max_onboard_minutes: int = Field(default=60, ge=1, le=240)
    search_seconds: int = Field(default=5, ge=1, le=30)

    @model_validator(mode="after")
    def unique_ids(self):
        if self.matrix is not None and self.matrix_id is not None:
            raise ValueError("Seleccione una sola matriz")
        if self.service_date == date.min:
            raise ValueError("Se requiere una fecha con día previo representable")
        for ids in (self.original_batch_ids, self.vehicle_ids, self.request_ids or []):
            if len(ids) != len(set(ids)):
                raise ValueError("Los IDs deben ser únicos")
        if not set(self.vehicle_origins) <= set(self.vehicle_ids):
            raise ValueError("Hay orígenes para vehículos ajenos al plan")
        return self


class UnassignedRequest(Schema):
    request_id: str
    reason: Literal[
        "excluded",
        "pending_review",
        "different_date",
        "unsupported_direction",
        "missing_schedule",
        "missing_pickup",
        "missing_terminal",
        "duplicate_identity",
        "no_compatible_vehicle",
        "unreachable_location",
        "joint_constraints",
        "search_limit",
    ]


class JointStop(Schema):
    request_id: str
    sequence: int
    pickup_at: datetime
    onboard_seconds: int


class JointTrip(Schema):
    vehicle_id: str
    driver_id: str
    trip_number: Literal[1, 2]
    customer_id: CustomerCode
    terminal_id: str
    dispatch_at: datetime
    arrival_at: datetime
    duration_seconds: int
    preparation_seconds: int
    empty_travel_seconds: int
    empty_travel_meters: int
    route_meters: int
    stops: list[JointStop]


class JointPlan(Schema):
    service_date: date
    status: Literal["complete", "partial", "infeasible", "search_limit"]
    solver_status: str
    preview: Literal[True] = True
    simulation: bool | None
    matrix_source: str | None
    matrix_verified_at: datetime | None = None
    matrix_id: str | None = None
    matrix_mode: Literal["synthetic", "static_road", "time_dependent"] | None = None
    trips: list[JointTrip]
    unassigned: list[UnassignedRequest]
    rules: PlanningRules | None = None
