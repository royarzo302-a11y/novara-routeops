"""Private ingestion domain, deliberately separate from the v0.1 routing input."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from app.models.schemas import ClockTime, Issue, Latitude, Longitude, Schema, Text, ValidationStatus


class CustomerCode(StrEnum):
    GRAN_AMERICA = "gran_america"
    LO_BLANCO = "lo_blanco"


class Customer(Schema):
    id: CustomerCode
    name: str


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    UNKNOWN = "unknown"


class DocumentRole(StrEnum):
    ORIGINAL = "original"
    INTERNAL = "internal"


class RequestField(StrEnum):
    EMPLOYEE_CODE = "employee_code"
    NAME = "name"
    ADDRESS = "address"
    COMMUNE = "commune"
    PHONE = "phone"
    SERVICE_DATE = "service_date"
    WORK_TIME = "work_time"
    END_TIME = "end_time"
    PICKUP_TIME = "pickup_time"
    ARRIVAL_TIME = "arrival_time"
    TERMINAL_NAME = "terminal_name"


class TerminalCreate(Schema):
    customer_id: CustomerCode
    name: Text
    address: Text | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Las coordenadas del terminal se proporcionan en pareja")
        return self


class Terminal(TerminalCreate):
    id: str


class CellEvidence(Schema):
    field: RequestField | None = None
    column: str
    raw_value: Any = None
    formula: str | None = None
    stored_value: Any = None
    origin: Literal["literal", "cached_unverified", "unresolved"]


class Provenance(Schema):
    document_sha256: str
    sheet_index: int
    row: int
    header_row: int
    block: int
    terminal_origin: Literal["none", "context", "source_match"] = "none"
    parser_version: Literal["0.2.0"] = "0.2.0"


class Correction(Schema):
    at: datetime
    actor: Literal["operator"] = "operator"
    reason: Text
    changes: dict[str, Any]
    previous_values: dict[str, Any]
    confirmed_fields: list[RequestField]


class RequestData(Schema):
    employee_code: Text | None = None
    name: Text | None = None
    address: Text | None = None
    commune: Text | None = None
    phone: Text | None = None
    service_date: date | None = None
    work_time: ClockTime | None = None
    end_time: ClockTime | None = None
    pickup_time: ClockTime | None = None
    arrival_time: ClockTime | None = None
    terminal_name: Text | None = None
    terminal_id: str | None = None
    direction: Direction = Direction.UNKNOWN
    excluded: bool = False

    @model_validator(mode="after")
    def civil_times(self):
        for field in ("work_time", "end_time", "pickup_time", "arrival_time"):
            value = getattr(self, field)
            if value and value.tzinfo:
                raise ValueError("Las horas deben ser civiles locales sin zona horaria")
        return self


class TransportRequest(RequestData):
    id: str
    batch_id: str
    customer_id: CustomerCode
    provenance: Provenance
    evidence: list[CellEvidence]
    validation_status: ValidationStatus = ValidationStatus.REVIEW
    issues: list[Issue] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)


class RequestPatch(RequestData):
    """Only explicitly supplied fields are changed; defaults never overwrite existing data."""


class ReviewRequest(Schema):
    changes: RequestPatch = Field(default_factory=RequestPatch)
    confirm_fields: list[RequestField] = Field(default_factory=list)
    reason: Text

    @model_validator(mode="after")
    def nonempty_review(self):
        if not self.changes.model_fields_set and not self.confirm_fields:
            raise ValueError("La revisión debe cambiar o confirmar al menos un campo")
        if (
            "direction" in self.changes.model_fields_set
            and self.changes.direction == Direction.UNKNOWN
        ):
            raise ValueError("Seleccione el sentido explícitamente")
        return self


class SheetReport(Schema):
    sheet_index: int
    category: str
    header_rows: list[int] = Field(default_factory=list)
    records: int = 0
    ignored_rows: dict[str, int] = Field(default_factory=dict)
    review_required: bool = False


class IngestionBatch(Schema):
    id: str
    customer_id: CustomerCode
    role: DocumentRole
    archive_date: date | None = None
    expected_service_date: date | None = None
    service_dates: list[date] = Field(default_factory=list)
    terminal_context_id: str | None = None
    document_sha256: str
    created_at: datetime
    profile_version: Literal["0.2.0"] = "0.2.0"
    records: int
    pending_review: int
    excluded: int
    unclassified_rows: int = 0
    status: Literal["interpreted", "pending_review"]
    sheets: list[SheetReport]


class UnclassifiedRow(Schema):
    id: str
    batch_id: str
    customer_id: CustomerCode
    provenance: Provenance
    cells: list[CellEvidence]
    validation_status: Literal["pending_review"] = "pending_review"


class IngestionResult(Schema):
    batch: IngestionBatch
    requests: list[TransportRequest]
    unclassified_rows: list[UnclassifiedRow] = Field(default_factory=list)


class ReconcileInput(Schema):
    original_batch_id: str
    internal_batch_id: str


class RecordMatch(Schema):
    original_id: str
    internal_id: str
    identity_basis: Literal["employee_code", "name_phone", "name_address"]
    provisional: bool
    different_fields: list[str]
    enriched_fields: list[str] = Field(default_factory=list)


class ReconciliationReport(Schema):
    id: str
    original_batch_id: str
    internal_batch_id: str
    created_at: datetime
    stale: bool = False
    status: Literal["reconciled", "pending_review"]
    original_records: int
    internal_records: int
    matches: list[RecordMatch]
    unmatched_original_ids: list[str]
    unmatched_internal_ids: list[str]
    ambiguous_groups: list[dict[str, list[str]]]
    difference_counts: dict[str, int]
    enrichment_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str]
