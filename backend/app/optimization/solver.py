from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.ingestion.excel import normalize
from app.models.schemas import (
    Depot,
    Driver,
    Issue,
    OptimizationRequest,
    OptimizationResult,
    Passenger,
    Route,
    Stop,
    Vehicle,
)
from app.optimization.travel import Location, TravelTimeProvider

LIMITATIONS = [
    "SIMULACIÓN: distancias y tiempos sintéticos, sin tráfico; no apta para operación real.",
    "Un viaje por vehículo y conductor; max_trips=2 es un límite superior, no habilita otro viaje.",
    "Cada van sale del depósito y termina en él; sin posición inicial real de conductores.",
    "Horas civiles locales de Santiago sin ajuste DST; confirmar reglas antes de producción.",
    "Primera solución factible determinista; no se garantiza optimalidad global.",
]


def solve(
    service_id: str,
    passengers: list[Passenger],
    vehicles: list[Vehicle],
    drivers: list[Driver],
    depot: Depot,
    config: OptimizationRequest,
    provider: TravelTimeProvider,
) -> OptimizationResult:
    if not passengers or len(passengers) > 100:
        raise ValueError("Optimización MVP admite entre 1 y 100 pasajeros")
    if any(p.issues or p.latitude is None or p.longitude is None for p in passengers):
        raise ValueError("Corrija todos los registros pendientes antes de optimizar")
    passengers = sorted(passengers, key=lambda p: (p.source_sheet, p.source_row, p.name))
    service_date = passengers[0].service_date
    if any(p.service_date != service_date for p in passengers):
        raise ValueError("Todos los pasajeros deben pertenecer a la misma fecha de servicio")
    base = datetime.combine(service_date, datetime.min.time()) - timedelta(days=1)

    def seconds(value):
        return int((datetime.combine(service_date, value) - base).total_seconds())

    def result(status, diagnostics, routes=None, solver_status="PRECHECK", affected=None):
        return OptimizationResult(
            id=str(uuid4()),
            service_id=service_id,
            created_at=datetime.now(UTC),
            status=status,
            config=config,
            routes=routes or [],
            solver_status=solver_status,
            diagnostics=diagnostics,
            affected_passenger_ids=affected if affected is not None else [p.id for p in passengers],
            limitations=LIMITATIONS,
        )

    by_vehicle = {d.vehicle_id: d for d in drivers if d.available}
    if len(by_vehicle) != sum(d.available for d in drivers):
        raise ValueError("MVP admite un único conductor disponible asignado a cada vehículo")
    fleet = [
        (v, by_vehicle[v.id])
        for v in sorted(vehicles, key=lambda v: v.identifier)
        if v.available and v.id in by_vehicle
    ]
    if not fleet or sum(v.capacity for v, _ in fleet) < len(passengers):
        return result(
            "infeasible",
            [
                Issue(
                    code="capacity",
                    message="Capacidad de vans con conductor disponible insuficiente "
                    "para todos los pasajeros en el modelo de un viaje",
                )
            ],
        )
    locations = [Location(depot.latitude, depot.longitude)] + [
        Location(p.latitude, p.longitude) for p in passengers
    ]
    matrix = provider.matrix(locations)
    matrix.validate(len(locations))
    if not matrix.simulation:
        raise ValueError(
            "MVP solo expone resultados de simulación; adapte validación para rutas reales"
        )
    # All-pairs shortest paths are lower bounds, including for non-metric directed matrices.
    lower = [row[:] for row in matrix.seconds]
    for k in range(len(lower)):
        for i in range(len(lower)):
            for j in range(len(lower)):
                lower[i][j] = min(lower[i][j], lower[i][k] + lower[k][j])
    windows = [
        (
            seconds(p.work_time)
            - config.arrival_buffer_minutes * 60
            - config.max_early_arrival_minutes * 60,
            seconds(p.work_time) - config.arrival_buffer_minutes * 60,
        )
        for p in passengers
    ]
    availability = []
    for _, d in fleet:
        start, end = seconds(d.available_from), seconds(d.available_until)
        if start > end:
            start -= 86400  # Overnight shift ending on the service date.
        availability.append((start, end))
    allowed = []
    diagnostics, affected = [], []
    for node, p in enumerate(passengers, start=1):
        possible = []
        for v, (vehicle, _) in enumerate(fleet):
            if vehicle.allowed_communes and normalize(p.commune) not in {
                normalize(c) for c in vehicle.allowed_communes
            }:
                continue
            start, end = availability[v]
            earliest, deadline = windows[node - 1]
            if end >= earliest and start + lower[0][node] + config.boarding_seconds + lower[node][
                0
            ] <= min(deadline, end):
                possible.append(v)
        allowed.append(possible)
        if lower[node][0] + config.boarding_seconds > config.max_onboard_minutes * 60:
            diagnostics.append(
                Issue(
                    code="onboard_time",
                    field=p.id,
                    message="Tiempo mínimo a bordo supera el máximo configurado",
                )
            )
            affected.append(p.id)
        if not possible:
            diagnostics.append(
                Issue(
                    code="eligibility",
                    field=p.id,
                    message="Sin van/conductor compatible con comuna, disponibilidad "
                    "y ventana de llegada",
                )
            )
            affected.append(p.id)
    if diagnostics:
        return result("infeasible", diagnostics, affected=sorted(set(affected)))
    manager = pywrapcp.RoutingIndexManager(len(locations), len(fleet), 0)
    routing = pywrapcp.RoutingModel(manager)

    def transit(from_index, to_index):
        origin, destination = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
        return matrix.seconds[origin][destination] + (config.boarding_seconds if origin else 0)

    callback = routing.RegisterTransitCallback(transit)
    routing.SetArcCostEvaluatorOfAllVehicles(callback)
    demand = routing.RegisterUnaryTransitCallback(
        lambda index: int(manager.IndexToNode(index) != 0)
    )
    routing.AddDimensionWithVehicleCapacity(demand, 0, [v.capacity for v, _ in fleet], True, "Load")
    # Zero waiting slack: passengers have destination windows only; dispatch can be delayed.
    routing.AddDimension(callback, 0, 172800, False, "Time")
    dimension = routing.GetDimensionOrDie("Time")
    solver = routing.solver()
    for v, (start, end) in enumerate(availability):
        dimension.CumulVar(routing.Start(v)).SetRange(start, end)
        dimension.CumulVar(routing.End(v)).SetRange(start, end)
        routing.AddVariableMinimizedByFinalizer(dimension.CumulVar(routing.End(v)))
        routing.AddVariableMinimizedByFinalizer(dimension.CumulVar(routing.Start(v)))
    for node, possible in enumerate(allowed, start=1):
        index = manager.NodeToIndex(node)
        # Scalar domain operations avoid the absl::Span binding issue in OR-Tools 9.15.
        routing.VehicleVar(index).SetRange(0, len(fleet) - 1)
        for v in range(len(fleet)):
            if v not in possible:
                routing.VehicleVar(index).RemoveValue(v)
        earliest, deadline = windows[node - 1]
        for v in possible:
            assigned = solver.IsEqualCstVar(routing.VehicleVar(index), v)
            end = dimension.CumulVar(routing.End(v))
            big_m = 345600
            solver.Add(end >= earliest - big_m * (1 - assigned))
            solver.Add(end <= deadline + big_m * (1 - assigned))
            solver.Add(
                end - dimension.CumulVar(index)
                <= config.max_onboard_minutes * 60 + big_m * (1 - assigned)
            )
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GREEDY_DESCENT
    params.solution_limit = 1
    params.time_limit.seconds = config.search_seconds
    assignment = routing.SolveWithParameters(params)
    status = routing.status()
    if assignment is None:
        proven = status == routing_enums_pb2.RoutingSearchStatus.ROUTING_INFEASIBLE
        return result(
            "infeasible" if proven else "no_solution",
            [
                Issue(
                    code="joint_constraints" if proven else "search_incomplete",
                    message=(
                        "Restricciones conjuntas incompatibles: capacidad, ventanas de llegada, "
                        "comunas, disponibilidad y tiempo a bordo. Revise los pasajeros indicados."
                        if proven
                        else "No se encontró solución dentro del límite. No demuestra "
                        "inviabilidad; amplíe el tiempo o revise restricciones conjuntas."
                    ),
                )
            ],
            solver_status=str(status),
        )
    routes = []
    for v, (vehicle, driver) in enumerate(fleet):
        index = routing.Start(v)
        next_index = assignment.Value(routing.NextVar(index))
        if routing.IsEnd(next_index):
            continue
        start = assignment.Value(dimension.CumulVar(index))
        end = assignment.Value(dimension.CumulVar(routing.End(v)))
        stops, distance = [], 0
        while not routing.IsEnd(index):
            next_index = assignment.Value(routing.NextVar(index))
            node = manager.IndexToNode(index)
            distance += matrix.meters[node][manager.IndexToNode(next_index)]
            if node:
                p = passengers[node - 1]
                pickup = assignment.Value(dimension.CumulVar(index))
                stops.append(
                    Stop(
                        passenger_id=p.id,
                        name=p.name,
                        address=p.address,
                        commune=p.commune,
                        work_time=p.work_time,
                        order=len(stops) + 1,
                        pickup_at=base + timedelta(seconds=pickup),
                        onboard_seconds=end - pickup,
                    )
                )
            index = next_index
        routes.append(
            Route(
                id=str(uuid4()),
                service_date=service_date,
                vehicle_id=vehicle.id,
                vehicle_identifier=vehicle.identifier,
                driver_id=driver.id,
                driver_identifier=driver.identifier,
                passenger_ids=[s.passenger_id for s in stops],
                stops=stops,
                departure_at=base + timedelta(seconds=start),
                arrival_at=base + timedelta(seconds=end),
                distance_meters=distance,
                duration_seconds=end - start,
                observations=[LIMITATIONS[0], matrix.source],
            )
        )
    return result("feasible", [], routes, str(status), affected=[])
