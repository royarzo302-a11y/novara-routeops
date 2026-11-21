from copy import deepcopy
from datetime import UTC, datetime
from io import BytesIO

from app.geo.service import GeoSettings
from app.main import create_app
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from .ingestion_builders import GA, ga_row, workbook
from .test_joint_planning import POINT, setup_api

AUTH = {"Authorization": "Bearer preparation-fixture"}
URL = "/v5/operator/preparation"


def test_saved_defaults_survive_restart_and_disambiguate_terminals_and_bases(tmp_path):
    url = f"sqlite:///{tmp_path / 'preparation.db'}"
    settings = GeoSettings(token="preparation-fixture")
    with TestClient(create_app(url, geo_settings=settings), headers=AUTH) as api:
        assert TestClient(api.app).get(URL).status_code == 401
        bases = [
            api.post(
                "/depots",
                json={
                    "name": f"Base {i}",
                    "address": "Ficticia",
                    "latitude": -33.4,
                    "longitude": -70.6,
                },
            ).json()
            for i in range(3)
        ]
        terminals = [
            api.post(
                "/v2/terminals",
                json={
                    "customer_id": "gran_america",
                    "name": f"Terminal {i}",
                    "latitude": -33.4,
                    "longitude": -70.6,
                },
            ).json()
            for i in range(2)
        ]
        body = {
            "depot_id": bases[1]["id"],
            "terminal_ids": {"gran_america": terminals[1]["id"]},
            "rules": {"max_onboard_minutes": 42},
        }
        assert api.put(URL, json=body).status_code == 200
        bad = deepcopy(body)
        bad["terminal_ids"] = {"lo_blanco": terminals[1]["id"]}
        assert api.put(URL, json=bad).status_code == 422
        assert api.put(URL, json={"rules": {"max_onboard_minutes": 0}}).status_code == 422
        result = api.post(
            "/v5/operator/ingestions/automatic",
            files={"file": ("fixture.xlsx", workbook([("Acercamiento", [GA, ga_row()])]))},
        )
        assert result.status_code == 201, result.text
        assert result.json()["requests"][0]["terminal_id"] == terminals[1]["id"]
    with TestClient(create_app(url, geo_settings=settings), headers=AUTH) as api:
        saved = api.get(URL).json()
        assert saved["depot_id"] == bases[1]["id"]
        assert saved["rules"]["max_onboard_minutes"] == 42
        assert saved["locked"] is False


def test_imported_road_matrix_requires_approvals_and_stales_when_coordinates_change():
    settings = GeoSettings(token="preparation-fixture")
    with TestClient(create_app("sqlite:///:memory:", geo_settings=settings), headers=AUTH) as api:
        plan, _ = setup_api(api)
        ids = list(plan.pop("pickup_points"))
        origins = {v: {k: POINT[k] for k in ("latitude", "longitude")} for v in plan["vehicle_ids"]}
        rides = [
            api.get(f"/v2/ingestions/{batch}").json()["requests"][0]
            for batch in plan["original_batch_ids"]
        ]
        keys = [
            *("pickup:" + rid for rid in ids),
            *("terminal:" + r["terminal_id"] for r in rides),
            *("origin:" + vid for vid in origins),
        ]
        cells = [[0 if i == j else 120 for j in range(len(keys))] for i in range(len(keys))]
        body = {
            "request_ids": ids,
            "vehicle_origins": origins,
            "matrix": {
                "source": "Fixture vial verificada",
                "verified_at": datetime.now(UTC).isoformat(),
                "location_keys": keys,
                "seconds": cells,
                "meters": cells,
            },
        }
        endpoint = "/v5/operator/matrices/import"
        assert api.post(endpoint, json=body).status_code == 422
        for rid in ids:
            assert (
                api.put(
                    f"/v4/geo/requests/{rid}/location",
                    json={"point": origins[plan["vehicle_ids"][0]], "reason": "Fixture"},
                ).status_code
                == 200
            )
        invalid = deepcopy(body)
        invalid["matrix"]["seconds"][0][1] = -1
        assert api.post(endpoint, json=invalid).status_code == 422
        imported = api.post(endpoint, json=body)
        assert imported.status_code == 201, imported.text
        matrix = imported.json()
        assert matrix["mode"] == "static_road" and not matrix["simulation"]
        plan["matrix_id"] = matrix["id"]
        plan["max_onboard_minutes"] = 42
        result = api.post("/v3/plans/preview", json=plan)
        assert result.status_code == 200, result.text
        assert result.json()["rules"]["max_onboard_minutes"] == 42
        assert datetime.fromisoformat(
            result.json()["matrix_verified_at"]
        ) == datetime.fromisoformat(body["matrix"]["verified_at"])
        exported = api.post("/v5/operator/plans/export", json=result.json())
        assert exported.status_code == 200, exported.text
        rows = dict(load_workbook(BytesIO(exported.content))["Supuestos"].values)
        assert rows["max_onboard_minutes"] == 42
        assert (
            api.put(
                f"/v4/geo/requests/{ids[0]}/location",
                json={
                    "point": {"latitude": -33.41, "longitude": -70.61},
                    "reason": "Cambio fixture",
                },
            ).status_code
            == 200
        )
        assert api.post("/v3/plans/preview", json=plan).status_code == 409


def test_demo_factors_are_read_only():
    app = create_app(
        "sqlite:///:memory:", geo_settings=GeoSettings(token="preparation-fixture", demo_mode=True)
    )
    with TestClient(app, headers=AUTH) as api:
        assert api.get(URL).json()["locked"] is True
        assert api.put(URL, json={}).status_code == 403
