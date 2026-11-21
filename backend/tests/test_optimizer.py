from datetime import datetime, time, timedelta

import pytest
from app.models.schemas import OptimizationRequest
from app.optimization.solver import solve
from app.optimization.travel import (
    Location,
    RealRoutingAdapter,
    SyntheticTravelTimeProvider,
    TravelMatrix,
)


def run(passengers, fleet, depot, **config):
    return solve(
        "service",
        passengers,
        *fleet,
        depot,
        OptimizationRequest(**config),
        SyntheticTravelTimeProvider(),
    )


def test_capacity_time_windows_and_onboard(passengers, fleet, depot):
    result = run(passengers, fleet, depot)
    assert result.status == "feasible"
    assigned = [s.passenger_id for r in result.routes for s in r.stops]
    assert sorted(assigned) == sorted(p.id for p in passengers)
    assert len({r.vehicle_id for r in result.routes}) == len(result.routes)
    assert len({r.driver_id for r in result.routes}) == len(result.routes)
    for route in result.routes:
        assert len(route.stops) <= 2
        assert route.duration_seconds == (route.arrival_at - route.departure_at).total_seconds()
        assert route.arrival_at >= route.departure_at
        assert route.departure_at.time() >= time(0)
        assert route.arrival_at.time() <= time(8)
        for stop in route.stops:
            deadline = datetime.combine(route.service_date, stop.work_time) - timedelta(minutes=10)
            assert deadline - timedelta(minutes=30) <= route.arrival_at <= deadline
            assert 0 <= stop.onboard_seconds <= 3600
            assert stop.onboard_seconds == (route.arrival_at - stop.pickup_at).total_seconds()
    # Independently verify each leg against the matrix, not just stored metrics.
    by_id = {p.id: p for p in passengers}
    for route in result.routes:
        locations = [Location(depot.latitude, depot.longitude)] + [
            Location(by_id[s.passenger_id].latitude, by_id[s.passenger_id].longitude)
            for s in route.stops
        ]
        matrix = SyntheticTravelTimeProvider().matrix(locations)
        previous = route.departure_at
        for i, stop in enumerate(route.stops, start=1):
            boarding = 60 if i > 1 else 0
            assert (stop.pickup_at - previous).total_seconds() == matrix.seconds[i - 1][
                i
            ] + boarding
            previous = stop.pickup_at
        assert (route.arrival_at - previous).total_seconds() == matrix.seconds[-1][0] + 60


def test_reproducible(passengers, fleet, depot):
    a, b = run(passengers, fleet, depot), run(passengers, fleet, depot)
    assert [(r.vehicle_id, r.passenger_ids, r.arrival_at) for r in a.routes] == [
        (r.vehicle_id, r.passenger_ids, r.arrival_at) for r in b.routes
    ]


def test_insufficient_capacity(passengers, fleet, depot):
    fleet[0][0].capacity = 1
    result = run(passengers, fleet, depot)
    assert result.status == "infeasible"
    assert result.diagnostics[0].code == "capacity"
    assert len(result.affected_passenger_ids) == 6


def test_unavailable_vehicle(passengers, fleet, depot):
    fleet[0][0].available = False
    assert run(passengers, fleet, depot).status == "infeasible"


def test_unavailable_driver(passengers, fleet, depot):
    fleet[1][0].available = False
    assert run(passengers, fleet, depot).status == "infeasible"


def test_driver_availability(passengers, fleet, depot):
    for driver in fleet[1]:
        driver.available_from = time(6)
    result = run(passengers, fleet, depot)
    assert result.status == "infeasible"
    assert any(i.code == "eligibility" for i in result.diagnostics)


def test_geography(passengers, fleet, depot):
    for vehicle in fleet[0]:
        vehicle.allowed_communes = ["Comuna incompatible"]
    assert run(passengers, fleet, depot).status == "infeasible"


def test_onboard_limit(passengers, fleet, depot):
    result = run(passengers, fleet, depot, max_onboard_minutes=1)
    assert result.status == "infeasible"
    assert any(i.code == "onboard_time" for i in result.diagnostics)


def test_incompatible_arrival_windows(passengers, fleet, depot):
    for i, passenger in enumerate(passengers):
        passenger.work_time = time(4 + i // 2, 30 * (i % 2))
    result = run(passengers, fleet, depot, max_early_arrival_minutes=0)
    assert result.status in {"no_solution", "infeasible"}
    assert not result.routes
    assert result.diagnostics


def test_overnight_pickups(passengers, fleet, depot):
    for passenger in passengers:
        passenger.work_time = time(0, 15)
    for driver in fleet[1]:
        driver.available_from, driver.available_until = time(22), time(2)
    result = run(passengers, fleet, depot)
    assert result.status == "feasible"
    assert any(s.pickup_at.date() < r.service_date for r in result.routes for s in r.stops)


def test_second_trip_explicitly_unsupported():
    with pytest.raises(ValueError):
        OptimizationRequest(max_trips_per_vehicle=2)


def test_matrix_contract():
    with pytest.raises(ValueError):
        TravelMatrix([[0, -1], [2, 0]], [[0]], "bad", True).validate(2)
    with pytest.raises(ValueError):
        TravelMatrix([[0.0]], [[0]], "bad", True).validate(1)
    matrix = SyntheticTravelTimeProvider().matrix([Location(-33.4, -70.6), Location(-33.5, -70.7)])
    matrix.validate(2)
    assert matrix.simulation and matrix.seconds[0][1] > 0
    with pytest.raises(ValueError, match="simulación"):
        RealRoutingAdapter(lambda _: matrix).matrix([Location(0, 0), Location(1, 1)])


def test_accumulated_onboard_constraint(passengers, fleet, depot):
    class FixedMatrix:
        def matrix(self, locations):
            seconds = [[0, 180, 180], [180, 0, 240], [180, 240, 0]]
            return TravelMatrix(
                seconds, [[value * 10 for value in row] for row in seconds], "synthetic_test", True
            )

    # Each passenger alone needs 4 min including boarding; together the first needs 9 min.
    config = OptimizationRequest(max_onboard_minutes=5)
    one_van = solve("s", passengers[:2], fleet[0][:1], fleet[1][:1], depot, config, FixedMatrix())
    assert one_van.status in {"no_solution", "infeasible"} and not one_van.routes
    two_vans = solve("s", passengers[:2], fleet[0][:2], fleet[1][:2], depot, config, FixedMatrix())
    assert two_vans.status == "feasible" and len(two_vans.routes) == 2
    assert all(s.onboard_seconds == 240 for route in two_vans.routes for s in route.stops)


def test_allowed_communes_assignment(passengers, fleet, depot):
    fleet[0][0].allowed_communes = ["SANTIAGO"]
    fleet[0][1].allowed_communes = ["San Miguel"]
    fleet[0][2].allowed_communes = ["La Cisterna", "San Joaquín"]
    result = run(passengers, fleet, depot)
    assert result.status == "feasible"
    for route in result.routes:
        vehicle = next(v for v in fleet[0] if v.id == route.vehicle_id)
        assert all(
            s.commune.lower() in [c.lower() for c in vehicle.allowed_communes] for s in route.stops
        )
