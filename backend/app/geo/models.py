from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.models.schemas import Latitude, Longitude, Schema, Text

TrafficMode = Literal["synthetic", "static_road", "time_dependent"]


class Point(Schema):
    latitude: Latitude
    longitude: Longitude


class AddressInput(Schema):
    model_config = ConfigDict(str_strip_whitespace=False)

    address: Text
    commune: Text
    city: Text = "Santiago"


class AddressCheck(AddressInput):
    normalized_address: str
    normalized_commune: str
    normalized_city: str
    issues: list[str]


class Candidate(Point):
    id: str
    context_match: bool


class Approval(Schema):
    candidate_id: str | None = None
    point: Point | None = None
    reason: Text

    @model_validator(mode="after")
    def one(self):
        if (self.candidate_id is None) == (self.point is None):
            raise ValueError("Seleccione un candidato o indique un punto manual")
        return self


class GeocodeQuery(Schema):
    city: Text = "Santiago"


class LocationReview(Schema):
    request_id: str
    address: AddressCheck | None
    status: Literal["pending", "review_required", "approved"]
    candidates: list[Candidate] = Field(default_factory=list)
    approved_point: Point | None = None
    approval_source: str | None = None
    approval_reason: str | None = None
    provider: str | None = None
    map_version: str | None = None
    updated_at: datetime


class MatrixInput(Schema):
    request_ids: list[str] = Field(min_length=1, max_length=60)
    vehicle_origins: dict[str, Point] = Field(min_length=1, max_length=3)
    departure_at: datetime | None = None

    @model_validator(mode="after")
    def validate_scope(self):
        if len(set(self.request_ids)) != len(self.request_ids):
            raise ValueError("Las solicitudes deben ser únicas")
        if self.departure_at and self.departure_at.utcoffset() is None:
            raise ValueError("Indique zona horaria para la salida")
        return self


class MatrixMetadata(Schema):
    id: str
    provider: str
    map_version: str
    upstream_data_version: str | None = None
    profile: str
    mode: TrafficMode
    simulation: bool
    generated_at: datetime
    departure_at: datetime | None
    location_keys: list[str]
    duration_unit: Literal["seconds"] = "seconds"
    distance_unit: Literal["meters"] = "meters"
    unreachable_pairs: int
    isolated_location_keys: list[str]


class MatrixRecord(MatrixMetadata):
    seconds: list[list[int | None]]
    meters: list[list[int | None]]
