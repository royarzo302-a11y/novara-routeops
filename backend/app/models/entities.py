from datetime import date

from sqlalchemy import JSON, Date, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DepotRow(Base):
    __tablename__ = "depots"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class OperationSettingsRow(Base):
    __tablename__ = "operation_settings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class VehicleRow(Base):
    __tablename__ = "vehicles"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    identifier: Mapped[str] = mapped_column(String, unique=True)
    payload: Mapped[dict] = mapped_column(JSON)


class DriverRow(Base):
    __tablename__ = "drivers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    identifier: Mapped[str] = mapped_column(String, unique=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id"), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ServiceRow(Base):
    __tablename__ = "services"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    client: Mapped[str] = mapped_column(String)
    service_date: Mapped[date] = mapped_column(Date)
    depot_id: Mapped[str] = mapped_column(ForeignKey("depots.id"))
    status: Mapped[str] = mapped_column(String)
    import_report: Mapped[dict] = mapped_column(JSON)


class PassengerRow(Base):
    __tablename__ = "passengers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class OptimizationRow(Base):
    __tablename__ = "optimizations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), index=True)
    stale: Mapped[bool] = mapped_column(default=False)
    payload: Mapped[dict] = mapped_column(JSON)


class CustomerRow(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)


class TerminalRow(Base):
    __tablename__ = "terminals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class IngestionBatchRow(Base):
    __tablename__ = "ingestion_batches"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class TransportRequestRow(Base):
    __tablename__ = "transport_requests"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("ingestion_batches.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    terminal_id: Mapped[str | None] = mapped_column(ForeignKey("terminals.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ReconciliationRow(Base):
    __tablename__ = "reconciliations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    original_batch_id: Mapped[str] = mapped_column(ForeignKey("ingestion_batches.id"), index=True)
    internal_batch_id: Mapped[str] = mapped_column(ForeignKey("ingestion_batches.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class UnclassifiedRowEntity(Base):
    __tablename__ = "unclassified_ingestion_rows"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("ingestion_batches.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class GeocodeCacheRow(Base):
    __tablename__ = "geocode_cache"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class LocationReviewRow(Base):
    __tablename__ = "location_reviews"
    id: Mapped[str] = mapped_column(ForeignKey("transport_requests.id"), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class GeoMatrixRow(Base):
    __tablename__ = "geo_matrices"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String, unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
