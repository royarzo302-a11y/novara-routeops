from datetime import UTC, datetime

import pytest
from app.geo.models import Candidate
from app.geo.providers import (
    GeoProviderError,
    NominatimProvider,
    OSRMProvider,
    SyntheticGeocodingProvider,
    check_address,
    local_base_url,
)
from app.geo.service import GeoSettings
from app.main import create_app
from app.optimization.travel import Location, TravelMatrix
from fastapi.testclient import TestClient

from .test_joint_planning import POINT, Matrix, ride, run, setup_api

AUTH = {"Authorization": "Bearer local-test-token"}
MATRIX = "/v4/geo/matrices"


class FixtureGeocoder(SyntheticGeocodingProvider):
    calls = 0

    def __init__(self):
        super().__init__(
            {
                "calle ficticia 101": [
                    Candidate(id="a", latitude=-33.41, longitude=-70.61, context_match=True),
                    Candidate(id="b", latitude=-33.42, longitude=-70.62, context_match=False),
                ]
            }
        )

    def candidates(self, address):
        self.calls += 1
        return super().candidates(address)


class FixtureRoad(Matrix):
    name = "fixture_road"
    version = "fixture-osm-extract"
    profile = "driving"
    cache_scope = "fixture-local"
    mode = "synthetic"
    calls = 0

    def matrix(self, locations, *, departure_at=None):
        self.calls += 1
        return super().matrix(locations)


def test_normalization_preserves_original_and_flags_incomplete_addresses():
    result = check_address("  Av.   Ficticia  21B  ", "  Ñuñoa ", "Santiago")
    assert result.normalized_address == "av. ficticia 21b"
    assert result.address == "  Av.   Ficticia  21B  "
    assert result.normalized_commune == "nunoa"
    assert not result.issues
    assert "ambiguous_address" in check_address("Calle Ficticia esquina otra", "A", "B").issues
    assert "incomplete_address" in check_address("Calle Ficticia", "A", "B").issues


@pytest.mark.parametrize(
    "url",
    [
        "https://nominatim.openstreetmap.org",
        "http://router.project-osrm.org",
        "http://8.8.8.8",
        "http://127.0.0.1@8.8.8.8",
        "http://localhost",
        "http://10.0.0.1/redirect",
        "file://127.0.0.1",
        "http://169.254.169.254",
    ],
)
def test_public_or_untrusted_provider_urls_are_rejected_before_network(url):
    with pytest.raises(ValueError, match="local"):
        local_base_url(url)


def test_environment_keeps_provider_disabled_until_authorized(monkeypatch):
    monkeypatch.setenv("NOVARA_OSRM_URL", "http://127.0.0.1:5000")
    monkeypatch.setenv("NOVARA_GEO_TOKEN", "fixture-token")
    monkeypatch.delenv("NOVARA_GEO_LOCAL_AUTHORIZED", raising=False)
    assert GeoSettings.from_env().road is None
    monkeypatch.setenv("NOVARA_GEO_LOCAL_AUTHORIZED", "1")
    monkeypatch.setenv("NOVARA_GEO_MAP_VERSION", "fixture")
    assert GeoSettings.from_env().road.version == "fixture"


def test_nominatim_uses_location_context_and_keeps_candidates_unapproved(monkeypatch):
    adapter = NominatimProvider("http://127.0.0.1:8080", "fixture")

    def respond(path, params):
        assert path == "/search" and params["countrycodes"] == "cl"
        assert "Santiago" in params["q"]
        return [
            {
                "lat": "-33.40",
                "lon": "-70.6",
                "address": {
                    "country_code": "cl",
                    "municipality": "Comuna Sintética",
                    "city": "Santiago",
                },
            },
            {"lat": "-33.35", "lon": "-70.5", "address": {"country_code": "cl"}},
            {"lat": 100, "lon": 20},
        ]

    monkeypatch.setattr(adapter.http, "get", respond)
    candidates = adapter.candidates(
        check_address("Calle Ficticia 101", "Comuna Sintética", "Santiago")
    )
    assert [c.context_match for c in candidates] == [True, False]


def test_osrm_preserves_asymmetry_units_and_unreachable_pairs(monkeypatch):
    provider = OSRMProvider("http://127.0.0.1:5000", "fixture")
    points = [Location(-33.4, -70.6), Location(-33.42, -70.63), Location(-33.43, -70.65)]

    def respond(path, params):
        assert path.startswith("/table/v1/driving/-70.6,-33.4;")
        assert params["annotations"] == "duration,distance"
        assert "fallback_speed" not in params
        return {
            "code": "Ok",
            "durations": [[0, 60.1, None], [95, 0, None], [None, None, 0]],
            "distances": [[0, 900.5, None], [1200, 0, None], [None, None, 0]],
        }

    monkeypatch.setattr(provider.http, "get", respond)
    matrix = provider.matrix(points)
    assert matrix.seconds[0] == [0, 61, None] and matrix.seconds[1][0] == 95
    assert matrix.meters[0][1] == 901 and not matrix.simulation
    monkeypatch.setattr(provider.http, "get", lambda *_: {"code": "Ok", "durations": [[0]]})
    with pytest.raises(GeoProviderError, match="incompleta"):
        provider.matrix(points)
    monkeypatch.setattr(provider.http, "get", lambda *_: {"code": "NoSegment"})
    with pytest.raises(GeoProviderError, match="sin acceso"):
        provider.matrix(points)


def test_osrm_geometry_uses_geojson_coordinate_order(monkeypatch):
    provider = OSRMProvider("http://127.0.0.1:5000", "fixture")

    def respond(path, params):
        assert path.startswith("/route/v1/")
        assert params["geometries"] == "geojson"
        return {"code": "Ok", "routes": [{"geometry": {"coordinates": [[-70.6, -33.4]]}}]}

    monkeypatch.setattr(provider.http, "get", respond)
    assert provider.geometry([Location(-33.4, -70.6)] * 2)[0].latitude == -33.4


def test_unreachable_legs_are_never_used_by_solver():
    class ClosedRoad(Matrix):
        def matrix(self, points):
            result = super().matrix(points)
            for i in range(len(points)):
                if i != 0:
                    result.seconds[0][i] = result.meters[0][i] = None
                    result.seconds[i][0] = result.meters[i][0] = None
            return result

    result = run([ride("a", "ga", "04:00"), ride("b", "lb", "05:00")], provider=ClosedRoad())
    assert result.status == "partial"
    assert [s.request_id for trip in result.trips for s in trip.stops] == ["b"]
    assert result.unassigned[0].request_id == "a"


def test_mismatched_missing_cells_and_dimensions_are_rejected():
    with pytest.raises(ValueError, match="nulas"):
        TravelMatrix([[0, None], [2, 0]], [[0, 4], [3, 0]], "test", True).validate(
            2, allow_unreachable=True
        )
    with pytest.raises(ValueError, match="Dimensiones"):
        TravelMatrix([[0]], [[0]], "test", True).validate(2, allow_unreachable=True)


def test_geo_api_disabled_and_token_guards_private_ingestion(client):
    body = {"address": "Calle Ficticia 101", "commune": "Comuna"}
    assert client.post("/v4/geo/addresses/validate", json=body).status_code == 503
    with TestClient(
        create_app("sqlite:///:memory:", geo_settings=GeoSettings(token="secret"))
    ) as api:
        assert api.post("/v4/geo/addresses/validate", json=body).status_code == 401
        assert api.get("/v2/ingestions").status_code == 401
        assert api.post("/v3/plans/preview", json={}).status_code == 401
        response = api.post(
            "/v4/geo/addresses/validate", json=body, headers={"Authorization": "Bearer secret"}
        )
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"


def test_local_geocoding_approval_and_matrix_cache_survive_restart(tmp_path):
    geocoder = FixtureGeocoder()
    road = FixtureRoad()
    settings = GeoSettings(
        token="local-test-token", geocoder=geocoder, road=road, allow_simulation=True
    )
    url = f"sqlite:///{tmp_path / 'geo.db'}"
    with TestClient(create_app(url, geo_settings=settings), headers=AUTH) as api:
        plan, _ = setup_api(api)
        rides = list(plan.pop("pickup_points"))
        origins = {v: {k: POINT[k] for k in ("latitude", "longitude")} for v in plan["vehicle_ids"]}
        matrix_input = {"request_ids": rides, "vehicle_origins": origins}
        assert api.post(MATRIX, json=matrix_input).status_code == 422
        for ride_id in rides:
            path = f"/v4/geo/requests/{ride_id}"
            result = api.post(f"{path}/candidates", json={}).json()
            assert result["status"] == "review_required" and len(result["candidates"]) == 2
            assert result["approved_point"] is None
            assert (
                api.put(
                    f"{path}/location",
                    json={
                        "candidate_id": "b",
                        "reason": "Fixture",
                    },
                ).status_code
                == 422
            )
            assert (
                api.put(
                    f"{path}/location",
                    json={
                        "point": {"latitude": 99, "longitude": -70},
                        "reason": "Fixture",
                    },
                ).status_code
                == 422
            )
            assert (
                api.put(
                    f"{path}/location",
                    json={
                        "candidate_id": "a",
                        "reason": "Confirmación ficticia",
                    },
                ).json()["status"]
                == "approved"
            )
        assert geocoder.calls == 1
        response = api.post(MATRIX, json=matrix_input)
        assert response.status_code == 201, response.text
        meta = response.json()
        assert meta["simulation"] and meta["mode"] == "synthetic"
        assert meta["duration_unit"] == "seconds" and meta["distance_unit"] == "meters"
        assert "seconds" not in meta
        assert api.get(f"{MATRIX}/{meta['id']}").json()["seconds"]
        assert api.get(f"{MATRIX}/{meta['id']}/metadata").json() == meta
    with TestClient(create_app(url, geo_settings=settings), headers=AUTH) as api:
        assert api.post(MATRIX, json=matrix_input).json()["id"] == meta["id"]
        assert road.calls == 1
        response = api.post("/v3/plans/preview", json=plan | {"matrix_id": meta["id"]})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["matrix_id"] == meta["id"] and result["simulation"]
        assert result["status"] == "complete"
        assert {t["customer_id"] for t in result["trips"]} == {"gran_america", "lo_blanco"}
        assert (
            api.put(
                f"/v4/geo/requests/{rides[0]}/location",
                json={
                    "point": {"latitude": -33.44, "longitude": -70.61},
                    "reason": "Ajuste ficticio",
                },
            ).status_code
            == 200
        )
        assert (
            api.post("/v3/plans/preview", json=plan | {"matrix_id": meta["id"]}).status_code == 409
        )
        assert api.post(MATRIX, json=matrix_input).json()["id"] != meta["id"]


def test_temporal_matrix_preserves_departure_but_solver_rejects_it():
    class Temporal(FixtureRoad):
        mode = "time_dependent"

        def __init__(self):
            super().__init__(simulation=False)

    road = Temporal()
    settings = GeoSettings(token="local-test-token", road=road)
    with TestClient(create_app("sqlite:///:memory:", geo_settings=settings), headers=AUTH) as api:
        plan, _ = setup_api(api)
        rides = list(plan.pop("pickup_points"))
        origins = {v: {k: POINT[k] for k in ("latitude", "longitude")} for v in plan["vehicle_ids"]}
        for ride_id in rides:
            assert (
                api.put(
                    f"/v4/geo/requests/{ride_id}/location",
                    json={
                        "point": origins[plan["vehicle_ids"][0]],
                        "reason": "Fixture",
                    },
                ).status_code
                == 200
            )
        request = {"request_ids": rides, "vehicle_origins": origins}
        assert api.post(MATRIX, json=request).status_code == 422
        timestamp = datetime(2026, 1, 1, 5, tzinfo=UTC)
        earlier = api.post(MATRIX, json=request | {"departure_at": timestamp.isoformat()}).json()
        later = api.post(
            MATRIX, json=request | {"departure_at": timestamp.replace(hour=6).isoformat()}
        )
        assert later.status_code == 201 and later.json()["id"] != earlier["id"] and road.calls == 2
        assert (
            api.post("/v3/plans/preview", json=plan | {"matrix_id": earlier["id"]}).status_code
            == 422
        )
