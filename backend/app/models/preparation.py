from pydantic import Field

from app.models.ingestion import CustomerCode
from app.models.schemas import Schema


class PlanningRules(Schema):
    preparation_seconds: int = Field(default=600, ge=0, le=7200)
    boarding_seconds: int = Field(default=60, ge=0, le=600)
    arrival_buffer_minutes: int = Field(default=10, ge=0, le=120)
    max_early_arrival_minutes: int = Field(default=30, ge=0, le=180)
    max_onboard_minutes: int = Field(default=60, ge=1, le=240)
    search_seconds: int = Field(default=3, ge=1, le=30)


class Preparation(Schema):
    depot_id: str | None = None
    terminal_ids: dict[CustomerCode, str] = Field(default_factory=dict)
    matrix_id: str | None = None
    rules: PlanningRules = Field(default_factory=PlanningRules)


class PreparationView(Preparation):
    locked: bool = False
