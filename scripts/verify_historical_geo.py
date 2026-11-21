"""Private read-only census, followed by wholly independent synthetic planning."""

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from app.geo.providers import SyntheticRoadProvider
from app.ingestion.real_excel import parse_real_excel
from app.models.ingestion import Direction, DocumentRole, Provenance, Terminal, TransportRequest
from app.models.joint_planning import JointPlanInput, VerifiedPoint
from app.models.schemas import Driver, Vehicle
from app.optimization.joint import Crew, solve_joint
from verify_private_ingestion import VALIDATION_CUTOFF, eligible_files

DEVELOPMENT_DAYS = (date(2026, 8, 1), date(2026, 10, 3))


def simulate(customers, day):
    requests, terminals, pickups = [], {}, {}
    for group, (customer, count) in enumerate(sorted(customers.items())):
        terminal_id = f"fixture-terminal-{group}"
        terminals[terminal_id] = Terminal(
            id=terminal_id,
            customer_id=customer,
            name="Terminal ficticio",
            latitude=-33.45 - group / 100,
            longitude=-70.65,
        )
        for i in range(count):
            request_id = f"fixture-{group}-{i}"
            requests.append(
                TransportRequest(
                    id=request_id,
                    customer_id=customer,
                    batch_id=f"fixture-{group}",
                    service_date=day,
                    terminal_id=terminal_id,
                    direction=Direction.INBOUND,
                    work_time="04:30" if i % 2 else "05:00",
                    commune="Comuna ficticia",
                    employee_code=request_id,
                    validation_status="valid",
                    provenance=Provenance(
                        document_sha256="fixture", sheet_index=1, row=i + 1, header_row=1, block=1
                    ),
                    evidence=[],
                )
            )
            pickups[request_id] = VerifiedPoint(
                latitude=-33.46 - group / 100 - i / 10000,
                longitude=-70.66,
                source="fixture",
            )
    ids = [f"van-{i}" for i in range(3)]
    crews = [
        Crew(
            Vehicle(id=v, identifier=v),
            Driver(
                id=f"fixture-driver-{v}",
                identifier=v,
                vehicle_id=v,
                max_trips=2,
            ),
        )
        for v in ids
    ]
    options = JointPlanInput(
        service_date=day,
        original_batch_ids=["fixture"],
        vehicle_ids=ids,
        pickup_points=pickups,
        vehicle_origins={
            v: VerifiedPoint(latitude=-33.47, longitude=-70.65, source="fixture") for v in ids
        },
        arrival_buffer_minutes=10,
        max_early_arrival_minutes=10,
    )
    result = solve_joint(
        requests, terminals, crews, options, SyntheticRoadProvider(), allow_simulation=True
    )
    return {
        "simulation": result.simulation,
        "status": result.status,
        "assigned": sum(len(t.stops) for t in result.trips),
        "unassigned": len(result.unassigned),
        "trips": len(result.trips),
        "vans_used": len({t.vehicle_id for t in result.trips}),
    }


def verify(root):
    files, _ = eligible_files(root)
    results = []
    for day in DEVELOPMENT_DAYS:
        if day >= VALIDATION_CUTOFF:
            raise ValueError("Jornada reservada")
        customers, totals = Counter(), Counter()
        for path, archived, customer, role in files:
            if archived != day or role != DocumentRole.ORIGINAL:
                continue
            original = path.read_bytes()
            result = parse_real_excel(original, customer, role, archive_date=day)
            totals["workbooks"] += 1
            totals["identified"] += result.batch.records
            totals["pending_ingestion"] += result.batch.pending_review
            totals["valid_ingestion"] += result.batch.records - result.batch.pending_review
            totals["quarantined"] += result.batch.unclassified_rows
            customers[customer] += sum(r.direction == Direction.INBOUND for r in result.requests)
            if original != path.read_bytes():
                raise ValueError("Libro modificado durante la lectura")
        if not totals["workbooks"] or not sum(customers.values()):
            raise ValueError("Faltan nóminas de desarrollo")
        results.append(
            {
                "archive_date": day.isoformat(),
                "historical_read_only": dict(totals),
                "historical_inbound_by_customer": dict(customers),
                "historical_plan": "pending_without_approved_locations",
                "synthetic_plan": simulate(customers, day),
            }
        )
    return results


if __name__ == "__main__":
    try:
        print(json.dumps(verify(Path("data/real")), indent=2))
    except Exception:
        print('{"verification_failed": true, "source_details_withheld": true}')
        sys.exit(1)
