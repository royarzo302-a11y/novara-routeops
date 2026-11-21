"""Provider boundaries. HTTP adapters talk only to explicitly configured local IPs."""

import ipaddress
import json
import math
import re
from collections.abc import Sequence
from datetime import datetime
from http.client import HTTPException
from typing import Protocol
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from app.geo.models import AddressCheck, Candidate, Point, TrafficMode
from app.ingestion.excel import normalize
from app.optimization.travel import Location, SyntheticTravelTimeProvider, TravelMatrix


class GeoProviderError(ValueError):
    pass


class GeocodingProvider(Protocol):
    name: str
    version: str
    cache_scope: str

    def candidates(self, address: AddressCheck) -> list[Candidate]: ...


class RouteGeometryProvider(Protocol):
    def geometry(self, points: Sequence[Location]) -> list[Point]: ...


class RoadMatrixProvider(Protocol):
    name: str
    version: str
    cache_scope: str
    profile: str
    mode: TrafficMode

    def matrix(
        self, locations: Sequence[Location], *, departure_at: datetime | None = None
    ) -> TravelMatrix: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GeoProviderError("Redirección del proveedor bloqueada")


def local_base_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        address = ipaddress.ip_address(parts.hostname or "")
        private = any(address in block for block in PRIVATE_NETWORKS)
        invalid = (
            parts.scheme not in {"http", "https"}
            or not private
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
            or (parts.port is not None and not parts.port)
        )
    except ValueError:
        invalid = True
    if invalid:
        raise ValueError("Configure un origen HTTP local con IP privada literal")
    return url.rstrip("/")


PRIVATE_NETWORKS = tuple(
    map(
        ipaddress.ip_network,
        (
            "127.0.0.0/8",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "::1/128",
        ),
    )
)


class LocalHttp:
    def __init__(self, origin: str):
        self.origin = local_base_url(origin)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def get(self, path: str, params: dict):
        try:
            url = f"{self.origin}{path}?{urlencode(params)}"
            req = Request(url, headers={"User-Agent": "NovaraRouteOps/0.4"})
            with self.opener.open(req, timeout=8) as response:
                data = response.read(4_000_001)
            if len(data) > 4_000_000:
                raise GeoProviderError("Respuesta cartográfica demasiado grande")
            return json.loads(data)
        except (OSError, ValueError, HTTPException):
            raise GeoProviderError("El proveedor local no devolvió datos utilizables") from None


def check_address(address, commune, city):
    normalized_address = " ".join(address.casefold().split())
    issues = []
    if len(normalize(address)) < 8 or not re.search(r"\b\d+[a-z]?\b", normalized_address):
        issues.append("incomplete_address")
    if re.search(r"(?:\bs/n\b|\besquina\b|\bentre\b|\?)", normalized_address):
        issues.append("ambiguous_address")
    if not normalize(commune) or not normalize(city):
        issues.append("missing_context")
    return AddressCheck(
        address=address,
        commune=commune,
        city=city,
        normalized_address=normalized_address,
        normalized_commune=normalize(commune),
        normalized_city=normalize(city),
        issues=issues,
    )


class NominatimProvider:
    name = "nominatim_local"

    def __init__(self, origin: str, version: str):
        self.http = LocalHttp(origin)
        self.cache_scope = self.http.origin
        self.version = version

    def candidates(self, address):
        rows = self.http.get(
            "/search",
            {
                "q": f"{address.normalized_address}, {address.commune}, {address.city}, Chile",
                "countrycodes": "cl",
                "addressdetails": 1,
                "format": "jsonv2",
                "limit": 5,
            },
        )
        if not isinstance(rows, list):
            raise GeoProviderError("Respuesta de búsqueda inválida")
        result = []
        for row in rows[:5]:
            try:
                contexts = row.get("address", {})
                commune = {
                    normalize(contexts.get(field))
                    for field in ("municipality", "county", "city_district", "suburb", "city")
                }
                city = {
                    normalize(contexts.get(field))
                    for field in ("city", "municipality", "state", "county", "town")
                }
                match = (
                    contexts.get("country_code") == "cl"
                    and address.normalized_commune in commune
                    and address.normalized_city in city
                )
                result.append(
                    Candidate(
                        id=str(uuid4()),
                        latitude=row["lat"],
                        longitude=row["lon"],
                        context_match=match,
                    )
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
        return result


def coordinates(points):
    return ";".join(f"{p.longitude},{p.latitude}" for p in points)


class OSRMProvider:
    name = "osrm_local"
    mode: TrafficMode = "static_road"

    def __init__(self, origin: str, version: str, profile: str = "driving"):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", profile):
            raise ValueError("Perfil OSRM inválido")
        self.http = LocalHttp(origin)
        self.cache_scope = self.http.origin
        self.version = version
        self.profile = profile

    def matrix(self, locations, *, departure_at=None):
        if departure_at is not None:
            raise GeoProviderError("OSRM estático no acepta hora de salida")
        data = self.http.get(
            f"/table/v1/{self.profile}/{coordinates(locations)}",
            {
                "annotations": "duration,distance",
                "radiuses": ";".join(["100"] * len(locations)),
            },
        )
        try:
            if data["code"] != "Ok":
                raise ValueError
            seconds = rounded(data["durations"])
            meters = rounded(data["distances"])
            data_version = data.get("data_version")
            matrix = TravelMatrix(
                seconds,
                meters,
                self.name,
                False,
                data_version if isinstance(data_version, str) else None,
            )
            matrix.validate(len(locations), allow_unreachable=True)
            return matrix
        except (KeyError, TypeError, ValueError, OverflowError):
            raise GeoProviderError(
                "Matriz OSRM incompleta, inválida o sin acceso a la vía"
            ) from None

    def geometry(self, points):
        data = self.http.get(
            f"/route/v1/{self.profile}/{coordinates(points)}",
            {
                "overview": "full",
                "geometries": "geojson",
                "radiuses": ";".join(["100"] * len(points)),
            },
        )
        try:
            if data["code"] != "Ok":
                raise ValueError
            return [
                Point(latitude=lat, longitude=lon)
                for lon, lat in data["routes"][0]["geometry"]["coordinates"]
            ]
        except (IndexError, KeyError, TypeError, ValueError):
            raise GeoProviderError("Geometría vial no disponible") from None


def rounded(table):
    def integer(value):
        if value is None:
            return None
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Valor de matriz inválido")
        return math.ceil(value)

    return [[integer(value) for value in row] for row in table]


class SyntheticRoadProvider(SyntheticTravelTimeProvider):
    name = "synthetic"
    version = "fixture-v1"
    cache_scope = "synthetic"
    profile = "driving"
    mode: TrafficMode = "synthetic"

    def matrix(self, locations, *, departure_at=None):
        return super().matrix(locations)


class SyntheticGeocodingProvider:
    """Lookup of explicitly supplied fixture candidates. Unknown inputs stay unresolved."""

    name = "synthetic_geocoding"
    version = "fixture-v1"
    cache_scope = "synthetic"

    def __init__(self, fixtures: dict[str, list[Candidate]]):
        self.fixtures = fixtures

    def candidates(self, address):
        return self.fixtures.get(address.normalized_address, [])
