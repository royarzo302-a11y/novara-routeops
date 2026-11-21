import json
from datetime import date
from pathlib import Path

import pytest
from app.ingestion.excel import parse_excel
from app.main import create_app
from app.models.schemas import Depot, Driver, Vehicle
from fastapi.testclient import TestClient

DATA = Path(__file__).resolve().parents[2] / "data" / "synthetic"
DAY = date(2026, 11, 20)


@pytest.fixture
def client():
    with TestClient(create_app("sqlite:///:memory:")) as api:
        yield api


@pytest.fixture
def passengers():
    return parse_excel((DATA / "case_d_feasible.xlsx").read_bytes(), "service", DAY)[0]


@pytest.fixture
def depot():
    payload = json.loads((DATA / "scenarios.json").read_text())["depot"]
    return Depot(id="depot", **payload)


@pytest.fixture
def fleet():
    vehicles = [Vehicle(id=f"v{i}", identifier=f"VAN-{i}", capacity=2) for i in range(3)]
    drivers = [
        Driver(id=f"d{i}", identifier=f"DRIVER-{i}", vehicle_id=v.id)
        for i, v in enumerate(vehicles)
    ]
    return vehicles, drivers


@pytest.fixture
def resources(client, depot):
    response = client.post("/depots", json=depot.model_dump(exclude={"id"}))
    assert response.status_code == 201
    for i in range(3):
        vehicle = client.post("/vehicles", json={"identifier": f"VAN-{i}", "capacity": 6}).json()
        driver = client.post(
            "/drivers", json={"identifier": f"DRIVER-{i}", "vehicle_id": vehicle["id"]}
        )
        assert driver.status_code == 201
    return response.json()


def import_case(client, depot_id, filename="case_d_feasible.xlsx"):
    return client.post(
        "/services/import",
        files={
            "file": (filename, (DATA / filename).read_bytes()),
        },
        data={"service_date": DAY.isoformat(), "depot_id": depot_id},
    )
