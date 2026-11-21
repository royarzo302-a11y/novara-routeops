from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from app.main import create_app
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from .conftest import DAY, import_case
from .test_ingestion import workbook_bytes


def test_health_docs_and_resources(client, resources):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    assert len(client.get("/vehicles").json()) == 3
    assert len(client.get("/drivers").json()) == 3
    assert client.get("/depots").json()[0]["id"] == resources["id"]


@pytest.mark.parametrize(
    "case", ["case_a_structured.xlsx", "case_b_messy.xlsx", "case_d_feasible.xlsx"]
)
def test_full_flow(client, resources, case):
    response = import_case(client, resources["id"], case)
    assert response.status_code == 201, response.text
    service = response.json()
    sid = service["id"]
    assert service["status"] == "imported"
    assert client.get(f"/services/{sid}").json()["passenger_ids"] == service["passenger_ids"]
    assert len(client.get("/services").json()) == 1
    assert client.get(f"/services/{sid}/validation-errors").json() == []
    response = client.post(f"/services/{sid}/optimize", json={})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "feasible", result
    assert result["simulation"]
    assert sum(len(r["stops"]) for r in result["routes"]) == len(service["passenger_ids"])
    plan_id = result["id"]
    assert client.get(f"/optimizations/{plan_id}").json() == result
    assert client.get(f"/services/{sid}/optimizations").json() == [result]
    assert client.get(f"/optimizations/{plan_id}/routes").json() == result["routes"]
    exported = client.get(f"/optimizations/{plan_id}/export")
    assert exported.status_code == 200
    workbook = load_workbook(BytesIO(exported.content))
    assert "SIMULACIÓN" in workbook.active["A1"].value
    assert workbook.active.max_row == 3 + len(service["passenger_ids"])
    assert "Supuestos" in workbook.sheetnames


def test_review_corrections_and_originals(client, resources):
    service = import_case(client, resources["id"], "case_c_errors.xlsx").json()
    sid = service["id"]
    assert service["status"] == "needs_review"
    errors = client.get(f"/services/{sid}/validation-errors").json()
    assert len(errors) == 6
    assert client.post(f"/services/{sid}/optimize", json={}).status_code == 422
    passengers = client.get(f"/services/{sid}/passengers").json()
    fixes = [
        {"address": "Calle Simulada 901"},
        {"work_time": "05:00"},
        {"name": "Persona sintética corregida 03"},
        {"latitude": -33.46},
        {"excluded": True},
    ]
    for passenger, correction in zip(passengers, fixes, strict=False):
        updated = client.patch(f"/passengers/{passenger['id']}", json=correction)
        assert updated.status_code == 200, updated.text
        assert updated.json()["original_values"] == passenger["original_values"]
    assert client.get(f"/services/{sid}/validation-errors").json() == []
    assert client.get(f"/services/{sid}").json()["status"] == "imported"
    # Duplicates were revalidated across the entire service, including the unedited twin.
    assert all(
        p["validation_status"] in {"valid", "excluded"}
        for p in client.get(f"/services/{sid}/passengers").json()
    )
    result = client.post(f"/services/{sid}/optimize", json={}).json()
    assert result["status"] == "feasible"
    assert sum(len(route["stops"]) for route in result["routes"]) == 5
    assert passengers[4]["id"] not in [
        stop["passenger_id"] for route in result["routes"] for stop in route["stops"]
    ]


def test_stale_plans_and_reoptimization(client, resources):
    service = import_case(client, resources["id"]).json()
    path = f"/services/{service['id']}/optimize"
    original = client.post(path, json={}).json()
    passenger = service["passenger_ids"][0]
    assert (
        client.patch(f"/passengers/{passenger}", json={"address": "Calle Simulada 999"}).status_code
        == 200
    )
    assert client.get(f"/optimizations/{original['id']}").json()["stale"]
    assert client.get(f"/optimizations/{original['id']}/export").status_code == 409
    replacement = client.post(path, json={}).json()
    assert replacement["status"] == "feasible" and not replacement["stale"]
    infeasible = client.post(path, json={"max_onboard_minutes": 1}).json()
    assert infeasible["status"] == "infeasible"
    assert client.get(f"/optimizations/{replacement['id']}/export").status_code == 409
    assert client.get(f"/optimizations/{infeasible['id']}/export").status_code == 409


def test_infeasible_fixture(client, resources):
    service = import_case(client, resources["id"], "case_e_infeasible.xlsx").json()
    response = client.post(f"/services/{service['id']}/optimize", json={"max_onboard_minutes": 1})
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "infeasible" and not result["routes"]
    assert result["affected_passenger_ids"]
    assert client.get(f"/services/{service['id']}").json()["status"] == "infeasible"


def test_http_errors(client, resources):
    for path in [
        "/services/missing",
        "/services/missing/passengers",
        "/services/missing/validation-errors",
        "/optimizations/missing",
    ]:
        assert client.get(path).status_code == 404
    assert (
        client.post("/vehicles", json={"identifier": "INVALID", "capacity": 0}).status_code == 422
    )
    assert client.post("/vehicles", json={"identifier": "VAN-0", "capacity": 5}).status_code == 409
    assert (
        client.post("/drivers", json={"identifier": "X", "vehicle_id": "unknown"}).status_code
        == 404
    )
    vehicle = client.get("/vehicles").json()[0]
    assert (
        client.post("/drivers", json={"identifier": "NEW", "vehicle_id": vehicle["id"]}).status_code
        == 409
    )
    data = {"service_date": DAY.isoformat(), "depot_id": resources["id"]}
    assert (
        client.post("/services/import", data=data, files={"file": ("x.csv", b"x")}).status_code
        == 415
    )
    assert (
        client.post("/services/import", data=data, files={"file": ("x.xlsx", b"x")}).status_code
        == 422
    )
    assert (
        client.post(
            "/services/import",
            data=data,
            files={
                "file": ("x.xlsx", b"x" * (10 * 1024 * 1024 + 1)),
            },
        ).status_code
        == 413
    )
    assert client.post("/services/missing/optimize", json={}).status_code == 404
    service = import_case(client, resources["id"]).json()
    pid = service["passenger_ids"][0]
    for patch in (
        {},
        {"work_time": 4},
        {"name": "Nombre\u0000inválido"},
        {"work_time": "4 o 5"},
        {"latitude": 100},
        {"service_date": None},
        {"service_date": "2026-11-21"},
        {"work_time": "04:00:00+03:00"},
    ):
        assert client.patch(f"/passengers/{pid}", json=patch).status_code == 422
    assert (
        client.post(
            f"/services/{service['id']}/optimize", json={"max_trips_per_vehicle": 2}
        ).status_code
        == 422
    )


def test_corrections_survive_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    with TestClient(create_app(url)) as client:
        depot = client.post(
            "/depots",
            json={
                "name": "SIM",
                "address": "Calle Simulada 100",
                "latitude": -33.45,
                "longitude": -70.65,
            },
        ).json()
        service = import_case(client, depot["id"]).json()
        pid = service["passenger_ids"][0]
        corrected = client.patch(f"/passengers/{pid}", json={"name": "Nombre corregido"})
        assert corrected.status_code == 200
    with TestClient(create_app(url)) as client:
        passengers = client.get(f"/services/{service['id']}/passengers").json()
        assert passengers[0]["name"] == "Nombre corregido"
        assert passengers[0]["original_values"] == corrected.json()["original_values"]


def test_formula_injection_export(client, resources):
    service = import_case(client, resources["id"]).json()
    pid = service["passenger_ids"][0]
    client.patch(f"/passengers/{pid}", json={"name": '=HYPERLINK("bad")'})
    result = client.post(f"/services/{service['id']}/optimize", json={}).json()
    response = client.get(f"/optimizations/{result['id']}/export")
    workbook = load_workbook(BytesIO(response.content))
    cells = [row[6] for row in workbook.active.iter_rows(min_row=4)]
    cell = next(cell for cell in cells if "HYPERLINK" in cell.value)
    assert cell.data_type == "s" and cell.value.startswith("'")


def test_source_review_resolution(client, resources):
    content = workbook_bytes(
        [
            ["Nombre", "Chofer", "Dirección", "Hora", "Fecha", "Comuna", "Lat", "Lon"],
            ["Uno", "Dos", "Calle Simulada 100", "04:00", "2026-11-21", "Santiago", -33.45, -70.65],
        ]
    )
    response = client.post(
        "/services/import",
        files={"file": ("ambiguous.xlsx", content)},
        data={"depot_id": resources["id"], "service_date": DAY.isoformat()},
    )
    service = response.json()
    pid = service["passenger_ids"][0]
    response = client.patch(
        f"/passengers/{pid}",
        json={
            "name": "Pasajero revisado",
            "service_date": DAY.isoformat(),
            "confirm_source_headers": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["validation_status"] == "valid"
    assert not response.json()["issues"]


def test_no_double_booking_across_services(client, resources):
    first = import_case(client, resources["id"], "case_a_structured.xlsx").json()
    result = client.post(f"/services/{first['id']}/optimize", json={}).json()
    assert result["status"] == "feasible" and len(result["routes"]) == 3
    second = import_case(client, resources["id"]).json()
    blocked = client.post(f"/services/{second['id']}/optimize", json={}).json()
    assert blocked["status"] == "infeasible"
    assert any(i["code"] == "reserved_resources" for i in blocked["diagnostics"])
    assert client.post(f"/services/{first['id']}/optimize", json={}).json()["status"] == "feasible"


def test_concurrent_planning_reserves_once(client, resources):
    services = [
        import_case(client, resources["id"], "case_a_structured.xlsx").json() for _ in range(2)
    ]

    def optimize(service):
        response = client.post(f"/services/{service['id']}/optimize", json={})
        assert response.status_code == 201
        return response.json()["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(optimize, services))
    assert sorted(statuses) == ["feasible", "infeasible"]
