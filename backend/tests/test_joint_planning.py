from datetime import UTC, date, datetime, time, timedelta

import pytest
from app.main import create_app
from app.models.ingestion import Terminal, TransportRequest
from app.models.joint_planning import JointPlanInput
from app.models.schemas import Driver, Vehicle
from app.optimization.joint import Crew, solve_joint
from app.optimization.travel import TravelMatrix
from fastapi.testclient import TestClient

from .ingestion_builders import DAY, GA, LB, ga_row, lb_row, workbook

POINT = {"latitude": -33.4, "longitude": -70.6, "source": "fixture"}
TERMINALS = {
    "ga": Terminal(id="ga", customer_id="gran_america", name="GA", latitude=-33.1, longitude=-70),
    "lb": Terminal(id="lb", customer_id="lo_blanco", name="LB", latitude=-33.2, longitude=-70),
}


class Matrix:
    def __init__(self, seconds=120, overrides=None, simulation=True):
        self.seconds = seconds
        self.overrides = overrides or {}
        self.simulation = simulation

    def matrix(self, points):
        seconds = [
            [
                0 if i == j else self.overrides.get((a.latitude, b.latitude), self.seconds)
                for j, b in enumerate(points)
            ]
            for i, a in enumerate(points)
        ]
        return TravelMatrix(
            seconds, [[s * 10 for s in row] for row in seconds], "fixture", self.simulation
        )


def ride(key, terminal, hour, **extra):
    return TransportRequest.model_validate(
        {
            "id": key,
            "batch_id": "batch",
            "customer_id": TERMINALS[terminal].customer_id,
            "terminal_id": terminal,
            "work_time": hour,
            "service_date": DAY,
            "direction": "inbound",
            "commune": "Zona A",
            "employee_code": key,
            "validation_status": "valid",
            "evidence": [],
            "provenance": {
                "document_sha256": "synthetic",
                "sheet_index": 1,
                "row": 2,
                "header_row": 1,
                "block": 1,
            },
            **extra,
        }
    )


def crew(key="1", capacity=12, **extra):
    vehicle = Vehicle(id=key, identifier=f"Van {key}", capacity=capacity, **extra)
    return Crew(
        vehicle, Driver(id=f"d{key}", identifier=f"Driver {key}", vehicle_id=key, max_trips=2)
    )


def run(rides, crews=None, provider=None, **extra):
    crews = crews or [crew(), crew("2", available=False), crew("3", available=False)]
    options = JointPlanInput.model_validate(
        {
            "service_date": DAY,
            "original_batch_ids": ["batch"],
            "vehicle_ids": ["1", "2", "3"],
            "pickup_points": {
                r.id: POINT | {"latitude": -34 - i / 100} for i, r in enumerate(rides)
            },
            "vehicle_origins": {c.vehicle.id: POINT for c in crews},
            "boarding_seconds": 0,
            "arrival_buffer_minutes": 0,
            "max_early_arrival_minutes": 0,
            **extra,
        }
    )
    return solve_joint(
        rides, TERMINALS, crews, options, provider or Matrix(), allow_simulation=True
    )


def test_two_trips_across_clients_with_directional_reposition():
    rides = [ride("a", "ga", "04:00"), ride("b", "lb", "05:00")]
    plan = run(rides, provider=Matrix(overrides={(-33.1, -34.01): 900}))
    assert plan.status == "complete" and plan.simulation
    first, second = plan.trips
    assert first.vehicle_id == second.vehicle_id == "1"
    assert first.driver_id == second.driver_id
    assert (first.trip_number, second.trip_number) == (1, 2)
    assert first.customer_id != second.customer_id
    assert second.empty_travel_seconds == 900
    assert second.stops[0].pickup_at - second.dispatch_at == timedelta(seconds=900)
    assert second.dispatch_at >= first.arrival_at + timedelta(seconds=600)


def test_reposition_and_preparation_each_can_prevent_reuse():
    rides = [ride("a", "ga", "04:00"), ride("b", "lb", "04:20")]
    assert run(rides).status == "complete"
    assert run(rides, preparation_seconds=1200).status == "partial"
    assert run(rides, provider=Matrix(overrides={(-33.1, -34.01): 1200})).status == "partial"


def test_three_vans_each_do_two_trips_and_no_third():
    rides = [ride(f"r{i}", "ga" if i % 2 else "lb", f"0{4 + i}:00") for i in range(4)]
    rides += [ride("r4", "ga", "08:00"), ride("r5", "lb", "08:00"), ride("r6", "ga", "03:00")]
    plan = run(rides, [crew(str(i), capacity=1) for i in range(1, 4)])
    assert plan.status == "partial"
    assert len(plan.trips) == 6
    assert len(plan.unassigned) == 1 and plan.unassigned[0].reason == "joint_constraints"
    for vehicle_id in ("1", "2", "3"):
        a, b = [t for t in plan.trips if t.vehicle_id == vehicle_id]
        assert a.arrival_at <= b.dispatch_at
        assert (a.trip_number, b.trip_number) == (1, 2)


def test_same_van_cannot_serve_both_clients_at_same_time():
    plan = run([ride("a", "ga", "04:00"), ride("b", "lb", "04:00")])
    assert len(plan.trips) == len(plan.unassigned) == 1


def test_windows_overlap_with_different_work_times_and_capacity():
    rides = [ride("a", "ga", "04:00"), ride("b", "ga", "04:10")]
    options = dict(max_early_arrival_minutes=20, arrival_buffer_minutes=5)
    plan = run(rides, **options)
    assert len(plan.trips) == 1
    (trip,) = plan.trips
    assert (
        datetime.combine(DAY, time(3, 45)) <= trip.arrival_at <= datetime.combine(DAY, time(3, 55))
    )
    assert [s.sequence for s in trip.stops] == [1, 2]
    capacity_plan = run(rides, [crew(capacity=1)], **options)
    assert all(len(t.stops) == 1 for t in capacity_plan.trips)
    assert len(capacity_plan.trips) == 2


def test_onboard_limit_and_zone_can_make_plan_infeasible():
    request = ride("a", "ga", "04:00")
    assert run([request], provider=Matrix(seconds=61), max_onboard_minutes=1).status == "infeasible"
    geo = run([request], [crew(allowed_communes=["Zona B"])])
    assert geo.unassigned[0].reason == "no_compatible_vehicle"
    assert geo.matrix_source is None


def test_onboard_limit_includes_boarding_and_each_intermediate_leg():
    rides = [ride("a", "ga", "04:00"), ride("b", "ga", "04:00")]
    plan = run(rides, max_onboard_minutes=4, boarding_seconds=10)
    assert len(plan.trips) == len(plan.unassigned) == 1
    assert plan.trips[0].stops[0].onboard_seconds == 130


def test_pending_and_outbound_are_reported():
    result = run(
        [
            ride("a", "ga", "04:00", validation_status="pending_review"),
            ride("b", "lb", "04:00", direction="outbound"),
            ride("c", "ga", "04:00", service_date=date(2026, 11, 9)),
        ]
    )
    assert [(u.request_id, u.reason) for u in result.unassigned] == [
        ("a", "pending_review"),
        ("b", "unsupported_direction"),
        ("c", "different_date"),
    ]


def setup_api(client):
    vehicle_ids = []
    for i in range(3):
        response = client.post("/vehicles", json={"identifier": f"Van {i}"})
        assert response.json()["capacity"] == 12
        vehicle_id = response.json()["id"]
        vehicle_ids.append(vehicle_id)
        assert (
            client.post(
                "/drivers",
                json={
                    "vehicle_id": vehicle_id,
                    "identifier": f"Conductor {i}",
                    "max_trips": 2,
                },
            ).status_code
            == 201
        )
    batches, pickup_ids, terminal_ids = [], [], []
    for customer, headers, row in (("gran_america", GA, ga_row()), ("lo_blanco", LB, lb_row())):
        terminal_id = client.post(
            "/v2/terminals",
            json={
                "customer_id": customer,
                "name": "Terminal Sintético",
                "latitude": -33.4,
                "longitude": -70.6,
            },
        ).json()["id"]
        terminal_ids.append(terminal_id)
        result = client.post(
            "/v2/ingestions",
            data={
                "customer_id": customer,
                "role": "original",
                "terminal_id": terminal_id,
            },
            files={"file": ("fixture.xlsx", workbook([("Acercamiento", [headers, row])]))},
        )
        assert result.status_code == 201
        batches.append(result.json()["batch"]["id"])
        pickup_ids.append(result.json()["requests"][0]["id"])
    body = {
        "service_date": DAY.isoformat(),
        "original_batch_ids": batches,
        "vehicle_ids": vehicle_ids,
        "pickup_points": dict.fromkeys(pickup_ids, POINT),
        "vehicle_origins": dict.fromkeys(vehicle_ids, POINT),
    }
    keys = [f"origin:{x}" for x in vehicle_ids]
    keys += [f"pickup:{x}" for x in pickup_ids] + [f"terminal:{x}" for x in terminal_ids]
    return body, keys


def test_joint_endpoint_reads_both_ingestion_profiles_and_attested_matrix(client):
    body, keys = setup_api(client)
    assert client.post("/v3/plans/preview", json=body).status_code == 422
    matrix = {
        "source": "Verificación ficticia para prueba",
        "verified_at": datetime.now(UTC).isoformat(),
        "location_keys": keys,
        "seconds": [[0 if i == j else 90 for j in range(len(keys))] for i in range(len(keys))],
        "meters": [[0 if i == j else 500 for j in range(len(keys))] for i in range(len(keys))],
    }
    response = client.post("/v3/plans/preview", json=body | {"matrix": matrix})
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["preview"] and plan["status"] == "complete" and not plan["simulation"]
    assert plan["matrix_verified_at"] and plan["matrix_source"] == matrix["source"]
    assert len(plan["trips"]) == 2
    assert {t["customer_id"] for t in plan["trips"]} == {"gran_america", "lo_blanco"}
    assert client.get("/services").json() == []


@pytest.mark.parametrize(("allow", "expected"), [(False, 422), (True, 200)])
def test_synthetic_provider_is_explicitly_test_only(allow, expected):
    app = create_app(
        "sqlite:///:memory:", joint_travel_provider=Matrix(), joint_allow_simulation=allow
    )
    with TestClient(app) as client:
        body, _ = setup_api(client)
        response = client.post("/v3/plans/preview", json=body)
        assert response.status_code == expected, response.text
        if allow:
            assert response.json()["simulation"] is True


def test_driver_limit_can_be_stricter_than_van_limit():
    pair = crew()
    pair.driver.max_trips = 1
    plan = run([ride("a", "ga", "04:00"), ride("b", "lb", "05:00")], [pair])
    assert plan.status == "partial"
    assert len(plan.trips) == 1


def test_overnight_driver_can_dispatch_on_previous_date():
    pair = crew()
    pair.driver.available_from, pair.driver.available_until = time(23), time(2)
    plan = run([ride("a", "ga", "00:01")], [pair])
    assert plan.status == "complete"
    assert plan.trips[0].dispatch_at.date() == DAY - timedelta(days=1)


def test_joint_preview_respects_existing_legacy_reservation(client):
    body, _ = setup_api(client)
    depot = client.post(
        "/depots",
        json={
            "name": "Sintético",
            "address": "Calle Ficticia 100",
            "latitude": -33.4,
            "longitude": -70.6,
        },
    ).json()
    content = workbook(
        [
            (
                "Legacy",
                [
                    ["Nombre", "Dirección", "Comuna", "Ingreso", "Lat", "Lon"],
                    ["Pasajero sintético", "Calle Ficticia 101", "Zona A", "05:00", -33.41, -70.61],
                ],
            )
        ]
    )
    legacy = client.post(
        "/services/import",
        data={
            "service_date": DAY.isoformat(),
            "depot_id": depot["id"],
        },
        files={"file": ("fixture.xlsx", content)},
    ).json()
    reservation = client.post(f"/services/{legacy['id']}/optimize", json={}).json()
    (assigned,) = reservation["routes"]
    vehicle_id = assigned["vehicle_id"]
    body["vehicle_origins"] = {vehicle_id: POINT}
    body["matrix"] = {
        "source": "Fixture",
        "verified_at": datetime.now(UTC).isoformat(),
        "location_keys": [f"origin:{vehicle_id}"],
        "seconds": [[0]],
        "meters": [[0]],
    }
    plan = client.post("/v3/plans/preview", json=body).json()
    assert plan["status"] == "infeasible" and plan["trips"] == []
    assert {u["reason"] for u in plan["unassigned"]} == {"no_compatible_vehicle"}
