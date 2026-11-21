from io import BytesIO

from app.geo.service import GeoSettings
from app.main import create_app
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from .test_joint_planning import ride, run


def test_operator_exports_exact_preview_and_rejects_unauthorized_access():
    plan = run([ride("=fixture", "ga", "04:00")])
    body = plan.model_dump(mode="json")
    app = create_app("sqlite:///:memory:", geo_settings=GeoSettings(token="fixture-token"))
    with TestClient(app) as api:
        url = "/v5/operator/plans/export"
        assert api.post(url, json=body).status_code == 401
        response = api.post(url, json=body, headers={"Authorization": "Bearer fixture-token"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        book = load_workbook(BytesIO(response.content))
        assert book.active["B1"].value == "Simulación"
        assert book.active["G4"].data_type == "s"
        assert book.active["G4"].value == "'=fixture"
        assert book.active["H4"].value == plan.trips[0].stops[0].pickup_at.isoformat()


def test_operator_resource_updates_and_development_cors():
    app = create_app("sqlite:///:memory:", geo_settings=GeoSettings(token="fixture-token"))
    with TestClient(app) as api:
        vehicle = api.post("/vehicles", json={"identifier": "Fixture"}).json()
        url = f"/v5/operator/vehicles/{vehicle['id']}"
        body = {"identifier": "Fixture", "capacity": 10, "available": False}
        assert api.put(url, json=body).status_code == 401
        headers = {"Authorization": "Bearer fixture-token"}
        assert api.put(url, json=body, headers=headers).status_code == 200
        assert api.get("/vehicles").json()[0]["capacity"] == 10
        for origin, status in [("http://localhost:5173", 200), ("https://other.invalid", 400)]:
            response = api.options(
                url,
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "PUT",
                    "Access-Control-Request-Headers": "Authorization, Content-Type",
                },
            )
            assert response.status_code == status
            assert ("access-control-allow-origin" in response.headers) == (status == 200)


def test_automatic_ingestion_uses_structure_and_reuses_approved_pickup():
    book = Workbook()
    sheet = book.active
    sheet.title = "Nómina"
    sheet.append(
        [
            "Fecha de presentación",
            "Hora de ingreso",
            "Código",
            "Nombre",
            "Dirección",
            "Comuna",
            "Teléfono",
            "Depósito asignado",
        ]
    )
    sheet.append(
        [
            "2026-11-20",
            "04:30",
            "DEMO-1",
            "Persona ficticia",
            "Calle Ficticia 101",
            "Santiago",
            "970000001",
            "Terminal de prueba",
        ]
    )
    output = BytesIO()
    book.save(output)
    files = {"file": ("gran-america.xlsx", output.getvalue())}
    url = "/v5/operator/ingestions/automatic"
    headers = {"Authorization": "Bearer fixture-token"}
    app = create_app("sqlite:///:memory:", geo_settings=GeoSettings(token="fixture-token"))
    with TestClient(app) as api:
        assert api.post(url, files=files).status_code == 401
        terminal = api.post(
            "/v2/terminals",
            headers=headers,
            json={
                "customer_id": "lo_blanco",
                "name": "Terminal de prueba",
                "latitude": -33.45,
                "longitude": -70.65,
            },
        ).json()
        response = api.post(url, files=files, headers=headers)
        assert response.status_code == 201
        item = response.json()["requests"][0]
        assert item["customer_id"] == "lo_blanco"
        assert item["service_date"] == "2026-11-20"
        assert item["terminal_id"] == terminal["id"]
        point = {"latitude": -33.41, "longitude": -70.61}
        rid = item["id"]
        approval = api.put(
            f"/v4/geo/requests/{rid}/location",
            headers=headers,
            json={
                "point": point,
                "reason": "Aprobación ficticia",
            },
        )
        assert approval.status_code == 200
        new_id = api.post(url, files=files, headers=headers).json()["requests"][0]["id"]
        prepared = api.post("/v5/operator/locations/prepare", headers=headers, json=[new_id])
        assert prepared.status_code == 200
        assert prepared.json()[new_id]["approved_point"] == point
