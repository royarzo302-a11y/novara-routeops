import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class TravelMatrix:
    seconds: list[list[int | None]]
    meters: list[list[int | None]]
    source: str
    simulation: bool
    data_version: str | None = None

    def validate(self, size: int, *, allow_unreachable: bool = False):
        for matrix in (self.seconds, self.meters):
            if len(matrix) != size or any(len(row) != size for row in matrix):
                raise ValueError("Dimensiones incorrectas en matriz de viaje")
            if any(
                type(value) is not int or value < 0
                for row in matrix
                for value in row
                if value is not None or not allow_unreachable
            ):
                raise ValueError("La matriz requiere enteros no negativos")
            if any(matrix[i][i] != 0 for i in range(size)):
                raise ValueError("La diagonal de la matriz debe ser cero")

        if any(
            (duration is None) != (distance is None)
            for durations, distances in zip(self.seconds, self.meters, strict=True)
            for duration, distance in zip(durations, distances, strict=True)
        ):
            raise ValueError("Los pares inaccesibles requieren duración y distancia nulas")


class TravelTimeProvider(Protocol):
    def matrix(self, locations: Sequence[Location]) -> TravelMatrix: ...


class SyntheticTravelTimeProvider:
    """SIMULATION: geodesic distance × 1.25 at constant 35 km/h; no traffic data."""

    def matrix(self, locations: Sequence[Location]) -> TravelMatrix:
        meters = []
        for origin in locations:
            row = []
            for dest in locations:
                lat1, lat2 = math.radians(origin.latitude), math.radians(dest.latitude)
                dlat = lat2 - lat1
                dlon = math.radians(dest.longitude - origin.longitude)
                a = math.sin(dlat / 2) ** 2 + (
                    math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                )
                row.append(round(6371000 * 2 * math.asin(min(1, math.sqrt(a))) * 1.25))
            meters.append(row)
        seconds = [[math.ceil(distance / (35000 / 3600)) for distance in row] for row in meters]
        return TravelMatrix(seconds, meters, "synthetic_geodesic_35kmh", True)


class RealRoutingAdapter:
    """Integration seam. Caller supplies a verified matrix client; not enabled in MVP API."""

    def __init__(self, fetch: Callable[[Sequence[Location]], TravelMatrix]):
        self.fetch = fetch

    def matrix(self, locations: Sequence[Location]) -> TravelMatrix:
        matrix = self.fetch(locations)
        matrix.validate(len(locations))
        if matrix.simulation:
            raise ValueError("El adaptador real recibió una simulación")
        return matrix


@dataclass(frozen=True)
class SubmittedMatrixProvider:
    """Offline matrix attested by the operator, indexed by request/terminal/vehicle IDs."""

    keys: list[str]
    travel: TravelMatrix
    verified_at: datetime | None

    def for_keys(self, keys: list[str]) -> TravelMatrix:
        self.travel.validate(len(self.keys), allow_unreachable=True)
        positions = {key: i for i, key in enumerate(self.keys)}
        if not set(keys) <= positions.keys():
            raise ValueError("Faltan ubicaciones requeridas en la matriz de viaje")
        indices = [positions[key] for key in keys]

        def subset(values):
            return [[values[i][j] for j in indices] for i in indices]

        return TravelMatrix(
            subset(self.travel.seconds),
            subset(self.travel.meters),
            self.travel.source,
            self.travel.simulation,
            self.travel.data_version,
        )
