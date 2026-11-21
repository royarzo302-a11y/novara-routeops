"""Joint inbound planning with two ordered slots per physical van."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from ortools.sat.python import cp_model

from app.ingestion.excel import normalize
from app.ingestion.real_excel import employee_identity
from app.models.ingestion import Direction, Terminal, TransportRequest
from app.models.joint_planning import (
    JointPlan,
    JointPlanInput,
    JointStop,
    JointTrip,
    UnassignedRequest,
)
from app.models.schemas import Driver, ValidationStatus, Vehicle
from app.optimization.travel import (
    Location,
    SubmittedMatrixProvider,
    TravelMatrix,
    TravelTimeProvider,
)

HORIZON = 172_799


@dataclass(frozen=True)
class Crew:
    vehicle: Vehicle
    driver: Driver


def clock(value):
    return 86_400 + value.hour * 3600 + value.minute * 60 + value.second


def eligibility(request, options, terminals, identities):
    if request.excluded:
        return "excluded"
    if request.validation_status != ValidationStatus.VALID or request.issues:
        return "pending_review"
    if request.service_date != options.service_date:
        return "different_date"
    if request.direction != Direction.INBOUND:
        return "unsupported_direction"
    if request.work_time is None:
        return "missing_schedule"
    if request.id not in options.pickup_points:
        return "missing_pickup"
    terminal = terminals.get(request.terminal_id)
    if (
        terminal is None
        or request.customer_id != terminal.customer_id
        or terminal.latitude is None
        or terminal.longitude is None
    ):
        return "missing_terminal"
    if identities[identity(request)] > 1:
        return "duplicate_identity"
    return None


def identity(request):
    return (
        request.customer_id,
        request.service_date,
        request.direction,
        employee_identity(request.employee_code) or request.id,
    )


@dataclass
class Slot:
    used: cp_model.IntVar
    start: cp_model.IntVar
    end: cp_model.IntVar
    terminal: cp_model.IntVar
    first: cp_model.IntVar
    visits: dict
    pickups: dict
    arcs: dict
    empty_seconds: cp_model.IntVar


def add_slot(model, crew, indices, rides, ends, matrix, options):
    size = len(matrix.seconds)
    used = model.new_bool_var("used")
    start = model.new_int_var(0, HORIZON, "first_pickup")
    end = model.new_int_var(0, HORIZON, "arrival")
    terminal = model.new_int_var(0, size - 1, "terminal_node")
    first = model.new_int_var(0, size - 1, "first_node")
    empty_seconds = model.new_int_var(0, HORIZON, "empty_seconds")
    visits = {i: model.new_bool_var("visit") for i in indices}
    pickups = {i: model.new_int_var(0, HORIZON, "pickup") for i in indices}
    arcs = {}
    edges = [(0, 0, ~used)]
    costs = []
    deadlines = {
        i: clock(rides[i].work_time) - options.arrival_buffer_minutes * 60 for i in indices
    }
    early = options.max_early_arrival_minutes * 60
    for i in indices:
        edges.append((i, i, ~visits[i]))
        deadline = deadlines[i]
        model.add(terminal == ends[i]).only_enforce_if(visits[i])
        model.add(end >= deadline - options.max_early_arrival_minutes * 60).only_enforce_if(
            visits[i]
        )
        model.add(end <= deadline).only_enforce_if(visits[i])
        model.add(end - pickups[i] <= options.max_onboard_minutes * 60).only_enforce_if(visits[i])
        model.add(end >= pickups[i]).only_enforce_if(visits[i])
        for j in [0, *indices]:
            if j == i or (j and (ends[i] != ends[j] or abs(deadline - deadlines[j]) > early)):
                continue
            dest = j or ends[i]
            duration = matrix.seconds[i][dest]
            if duration is None:
                continue
            arc = arcs[i, j] = model.new_bool_var("drive")
            edges.append((i, j, arc))
            arrival = pickups[j] if j else end
            model.add(arrival == pickups[i] + options.boarding_seconds + duration).only_enforce_if(
                arc
            )
            costs.append(arc * duration)
        arc = arcs[0, i] = model.new_bool_var("first")
        edges.append((0, i, arc))
        model.add(first == i).only_enforce_if(arc)
        model.add(start == pickups[i]).only_enforce_if(arc)
    # Circuit node indices must be dense even for vehicles with restricted zones.
    node_ids = {node: pos for pos, node in enumerate([0, *indices])}
    model.add_circuit([(node_ids[i], node_ids[j], arc) for i, j, arc in edges])
    model.add(sum(visits.values()) <= min(12, crew.vehicle.capacity) * used)
    model.add(sum(visits.values()) >= used)
    model.add(empty_seconds == 0).only_enforce_if(~used)
    model.add(first == 0).only_enforce_if(~used)
    model.add(terminal == 0).only_enforce_if(~used)
    return Slot(used, start, end, terminal, first, visits, pickups, arcs, empty_seconds), costs


def add_sequence(model, slots, crew, origin, matrix, options, ends):
    available_from = clock(crew.driver.available_from)
    available_until = clock(crew.driver.available_until)
    if available_from > available_until:
        available_from -= 86_400
    first = slots[0]
    model.add_allowed_assignments(
        [first.first, first.empty_seconds],
        [
            (pickup, matrix.seconds[origin][pickup])
            for pickup in first.visits
            if matrix.seconds[origin][pickup] is not None
        ],
    ).only_enforce_if(first.used)
    model.add(first.start - first.empty_seconds >= available_from).only_enforce_if(first.used)
    if len(slots) == 2:
        second = slots[1]
        model.add_implication(second.used, first.used)
        model.add_allowed_assignments(
            [first.terminal, second.first, second.empty_seconds],
            [
                (end, pickup, matrix.seconds[end][pickup])
                for end in sorted({ends[i] for i in first.visits})
                for pickup in second.visits
                if matrix.seconds[end][pickup] is not None
            ],
        ).only_enforce_if(second.used)
        model.add(
            second.start >= first.end + options.preparation_seconds + second.empty_seconds
        ).only_enforce_if(second.used)
    for slot in slots:
        model.add(slot.end <= available_until).only_enforce_if(slot.used)


def solve_joint(
    requests: list[TransportRequest],
    terminals: dict[str, Terminal],
    crews: list[Crew],
    options: JointPlanInput,
    provider: TravelTimeProvider | SubmittedMatrixProvider,
    *,
    allow_simulation=False,
):
    if len({r.id for r in requests}) != len(requests):
        raise ValueError("Las solicitudes deben ser únicas")
    if not {c.vehicle.id for c in crews} <= set(options.vehicle_ids) or (
        len({c.vehicle.id for c in crews}) != len(crews)
        or len({c.driver.id for c in crews}) != len(crews)
        or any(c.driver.vehicle_id != c.vehicle.id for c in crews)
    ):
        raise ValueError("La flota requiere pares únicos de van y conductor asignado")
    identities = Counter(identity(r) for r in requests if not r.excluded)
    unassigned = []
    candidates = []
    crews = [
        c
        for c in crews
        if c.vehicle.available and c.driver.available and c.vehicle.id in options.vehicle_origins
    ]
    zones = {c.vehicle.id: {normalize(zone) for zone in c.vehicle.allowed_communes} for c in crews}

    def compatible(crew, request):
        allowed = zones[crew.vehicle.id]
        return not allowed or normalize(request.commune) in allowed

    for request in requests:
        reason = eligibility(request, options, terminals, identities)
        if not reason and not any(compatible(c, request) for c in crews):
            reason = "no_compatible_vehicle"
        if reason:
            unassigned.append(UnassignedRequest(request_id=request.id, reason=reason))
        else:
            candidates.append(request)
    if not candidates:
        return JointPlan(
            service_date=options.service_date,
            status="infeasible" if requests else "complete",
            solver_status="PRECHECK",
            simulation=None,
            matrix_source=None,
            trips=[],
            unassigned=unassigned,
        )
    if len(candidates) > 60:
        raise ValueError("Máximo 60 solicitudes elegibles por jornada")
    rides = dict(enumerate(candidates, start=1))
    # Node zero is a dummy circuit vertex. The provider never receives it.
    terminal_ids = sorted({r.terminal_id for r in candidates})
    terminal_nodes = {tid: len(rides) + 1 + pos for pos, tid in enumerate(terminal_ids)}
    ends = {i: terminal_nodes[r.terminal_id] for i, r in rides.items()}
    origins = {
        c.vehicle.id: len(rides) + len(terminal_ids) + 1 + pos for pos, c in enumerate(crews)
    }
    keys = [f"pickup:{r.id}" for r in candidates] + [f"terminal:{t}" for t in terminal_ids]
    keys += [f"origin:{c.vehicle.id}" for c in crews]
    points = [options.pickup_points[r.id] for r in candidates] + [
        terminals[t] for t in terminal_ids
    ]
    points += [options.vehicle_origins[c.vehicle.id] for c in crews]
    if isinstance(provider, SubmittedMatrixProvider):
        actual = provider.for_keys(keys)
    else:
        actual = provider.matrix([Location(p.latitude, p.longitude) for p in points])
    actual.validate(len(keys), allow_unreachable=True)
    if actual.simulation and not allow_simulation:
        raise ValueError("La planificación v0.3 requiere una matriz verificada")
    if not actual.source.strip():
        raise ValueError("La matriz requiere una fuente")
    # Durations outside the full planning horizon cannot be traversed. Cap them for CP-SAT.

    matrix = TravelMatrix(
        [[0] * (len(keys) + 1)]
        + [
            [0, *(min(v, HORIZON + 1) if v is not None else None for v in row)]
            for row in actual.seconds
        ],
        [[0] * (len(keys) + 1)] + [[0, *row] for row in actual.meters],
        actual.source,
        actual.simulation,
    )
    model = cp_model.CpModel()
    fleet_slots = []
    costs = []
    visits = {i: [] for i in rides}
    for crew in crews:
        allowed = [i for i, r in rides.items() if compatible(crew, r)]
        slots = []
        for _ in range(min(2, crew.driver.max_trips)):
            slot, drive_costs = add_slot(model, crew, allowed, rides, ends, matrix, options)
            slots.append(slot)
            costs.extend([*drive_costs, slot.empty_seconds, slot.used])
            for i, visit in slot.visits.items():
                visits[i].append(visit)
        add_sequence(model, slots, crew, origins[crew.vehicle.id], matrix, options, ends)
        fleet_slots.append((crew, slots))
    for assigned in visits.values():
        model.add(sum(assigned) <= 1)
    # Every used slot fits in HORIZON, so this bound makes coverage the primary objective.
    weight = 6 * (HORIZON + 1) + 1
    model.maximize(weight * sum(v for group in visits.values() for v in group) - sum(costs))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = options.search_seconds
    solver.parameters.num_search_workers = 1
    status = solver.solve(model)
    if status == cp_model.MODEL_INVALID:
        raise RuntimeError("Modelo de planificación inválido")
    trips, assigned = [], set()
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        trips, assigned = extract(
            solver, fleet_slots, rides, terminals, terminal_nodes, origins, matrix, options
        )
    optimal = status == cp_model.OPTIMAL
    unassigned.extend(
        UnassignedRequest(
            request_id=r.id,
            reason="unreachable_location"
            if all(value is None for j, value in enumerate(matrix.seconds[i]) if j not in (0, i))
            or all(row[i] is None for j, row in enumerate(matrix.seconds) if j not in (0, i))
            else "joint_constraints"
            if optimal
            else "search_limit",
        )
        for i, r in rides.items()
        if i not in assigned
    )
    outcome = (
        "complete"
        if not unassigned
        else ("partial" if trips else "infeasible" if optimal else "search_limit")
    )
    return JointPlan(
        service_date=options.service_date,
        status=outcome,
        solver_status=solver.status_name(status),
        simulation=actual.simulation,
        matrix_source=actual.source,
        trips=trips,
        unassigned=unassigned,
        matrix_verified_at=provider.verified_at
        if isinstance(provider, SubmittedMatrixProvider)
        else None,
    )


def extract(solver, fleet_slots, rides, terminals, terminal_nodes, origins, matrix, options):
    base = datetime.combine(options.service_date - timedelta(days=1), datetime.min.time())

    def at(seconds):
        return base + timedelta(seconds=seconds)

    trips, assigned = [], set()
    terminal_ids = {node: tid for tid, node in terminal_nodes.items()}
    for crew, slots in fleet_slots:
        previous_node = origins[crew.vehicle.id]
        for number, slot in enumerate(slots, start=1):
            if not solver.value(slot.used):
                continue
            first = solver.value(slot.first)
            arrival = solver.value(slot.end)
            terminal_node = solver.value(slot.terminal)
            stops = []
            meters = 0
            current = first
            while current:
                pickup = solver.value(slot.pickups[current])
                stops.append(
                    JointStop(
                        request_id=rides[current].id,
                        sequence=len(stops) + 1,
                        pickup_at=at(pickup),
                        onboard_seconds=arrival - pickup,
                    )
                )
                assigned.add(current)
                next_node = next(
                    j for (i, j), arc in slot.arcs.items() if i == current and solver.value(arc)
                )
                meters += matrix.meters[current][next_node or terminal_node]
                current = next_node
            empty = solver.value(slot.empty_seconds)
            tid = terminal_ids[terminal_node]
            trips.append(
                JointTrip(
                    vehicle_id=crew.vehicle.id,
                    driver_id=crew.driver.id,
                    trip_number=number,
                    customer_id=terminals[tid].customer_id,
                    terminal_id=tid,
                    dispatch_at=at(solver.value(slot.start) - empty),
                    arrival_at=at(arrival),
                    duration_seconds=arrival - (solver.value(slot.start) - empty),
                    preparation_seconds=options.preparation_seconds if number == 2 else 0,
                    empty_travel_seconds=empty,
                    empty_travel_meters=matrix.meters[previous_node][first],
                    route_meters=meters,
                    stops=stops,
                )
            )
            previous_node = terminal_node
    return trips, assigned
