from datetime import date, datetime, time
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

Text = Annotated[
    str, Field(min_length=1, max_length=300, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]+$")
]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]


def explicit_clock_time(value):
    if not isinstance(value, (str, time)):
        raise ValueError("Use una hora local explícita HH:MM; no se aceptan números ambiguos")
    return value


ClockTime = Annotated[time, BeforeValidator(explicit_clock_time)]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


class ValidationStatus(StrEnum):
    VALID = "valid"
    REVIEW = "pending_review"
    EXCLUDED = "excluded"


class Issue(Schema):
    code: str
    field: str | None = None
    message: str
    severity: Literal["error", "warning"] = "error"


class PassengerData(Schema):
    name: Text | None = None
    address: Text | None = None
    commune: Text | None = None
    work_time: ClockTime | None = None
    service_date: date
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    excluded: bool = False

    @model_validator(mode="after")
    def local_time(self):
        if self.work_time and self.work_time.tzinfo:
            raise ValueError("work_time debe ser una hora local sin zona")
        return self


class PassengerPatch(Schema):
    name: Text | None = None
    address: Text | None = None
    commune: Text | None = None
    work_time: ClockTime | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    service_date: date | None = None
    confirm_source_headers: bool = False
    excluded: bool = False

    @model_validator(mode="after")
    def local_time(self):
        if self.work_time and self.work_time.tzinfo:
            raise ValueError("work_time debe ser una hora local sin zona")
        return self


class Passenger(PassengerData):
    id: str
    service_id: str
    validation_status: ValidationStatus
    issues: list[Issue]
    original_values: dict
    source_sheet: str
    source_row: int


class VehicleCreate(Schema):
    identifier: Text
    capacity: int = Field(default=12, ge=1, le=100)
    available: bool = True
    allowed_communes: list[Text] = Field(default_factory=list)


class Vehicle(VehicleCreate):
    id: str


class DriverCreate(Schema):
    identifier: Text
    vehicle_id: str
    available_from: ClockTime = time(0)
    available_until: ClockTime = time(8)
    max_trips: int = Field(default=1, ge=1, le=2)
    available: bool = True

    @model_validator(mode="after")
    def availability(self):
        if self.available_from.tzinfo or self.available_until.tzinfo:
            raise ValueError("Disponibilidad debe expresarse en horas locales sin zona")
        if self.available_from == self.available_until:
            raise ValueError("Inicio y fin de disponibilidad deben ser distintos")
        return self


class Driver(DriverCreate):
    id: str


class DepotCreate(Schema):
    name: Text
    address: Text
    latitude: Latitude
    longitude: Longitude


class Depot(DepotCreate):
    id: str


class Service(Schema):
    id: str
    client: str
    service_date: date
    depot_id: str
    status: Literal["imported", "needs_review", "planned", "infeasible", "no_solution"]
    passenger_ids: list[str]
    import_report: dict


class OptimizationRequest(Schema):
    max_onboard_minutes: int = Field(default=60, ge=1, le=240)
    arrival_buffer_minutes: int = Field(default=10, ge=0, le=120)
    max_early_arrival_minutes: int = Field(default=30, ge=0, le=180)
    boarding_seconds: int = Field(default=60, ge=0, le=600)
    search_seconds: int = Field(default=3, ge=1, le=30)
    max_trips_per_vehicle: Literal[1] = 1
    provider: Literal["synthetic"] = "synthetic"


class Stop(Schema):
    passenger_id: str
    name: str
    address: str
    commune: str
    work_time: time
    order: int
    pickup_at: datetime
    onboard_seconds: int


class Route(Schema):
    id: str
    service_date: date
    vehicle_id: str
    vehicle_identifier: str
    driver_id: str
    driver_identifier: str
    trip_number: Literal[1] = 1
    passenger_ids: list[str]
    stops: list[Stop]
    departure_at: datetime
    arrival_at: datetime
    distance_meters: int
    duration_seconds: int
    validation_status: Literal["simulation_only"] = "simulation_only"
    observations: list[str]


class OptimizationResult(Schema):
    id: str
    service_id: str
    created_at: datetime
    status: Literal["feasible", "infeasible", "no_solution"]
    simulation: Literal[True] = True
    provider: str = "synthetic"
    stale: bool = False
    solver_status: str
    config: OptimizationRequest
    routes: list[Route]
    diagnostics: list[Issue]
    affected_passenger_ids: list[str]
    limitations: list[str]
