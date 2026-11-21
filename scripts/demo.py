"""Exercise an already running API with fictitious data only."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1] / "data" / "synthetic"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--case", choices=list("ABCDE"), default="D")
    parser.add_argument("--output", type=Path, default=Path("/tmp/novara-simulation.xlsx"))
    args = parser.parse_args()
    scenario = json.loads((ROOT / "scenarios.json").read_text())
    case = scenario["cases"][args.case]
    suffix = uuid4().hex[:8]
    with httpx.Client(base_url=args.base_url, timeout=60) as api:

        def post(url, **kwargs):
            response = api.post(url, **kwargs)
            response.raise_for_status()
            return response.json()

        depot = post("/depots", json=scenario["depot"])
        # Reuse existing fleet to keep repeated demos within the MVP's single-trip model.
        vehicles = api.get("/vehicles").json()
        for i in range(max(0, 3 - len(vehicles))):
            vehicle = post(
                "/vehicles",
                json={
                    "identifier": f"SIM-VAN-{suffix}-{i + 1}",
                    "capacity": scenario["fleet"]["capacity_each"],
                },
            )
            post(
                "/drivers",
                json={
                    "identifier": f"SIM-CONDUCTOR-{suffix}-{i + 1}",
                    "vehicle_id": vehicle["id"],
                    "max_trips": 1,
                },
            )
        with (ROOT / case["file"]).open("rb") as source:
            service = post(
                "/services/import",
                files={"file": (case["file"], source)},
                data={
                    "service_date": scenario["service_date"],
                    "depot_id": depot["id"],
                },
            )
        print(f"Servicio: {service['id']} — {service['status']}")
        if service["status"] == "needs_review":
            response = api.get(f"/services/{service['id']}/validation-errors")
            response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))
            return
        result = post(f"/services/{service['id']}/optimize", json=case["config"])
        print(f"Resultado: {result['status']} — {len(result['routes'])} rutas SIMULADAS")
        if result["status"] == "feasible":
            response = api.get(f"/optimizations/{result['id']}/export")
            response.raise_for_status()
            args.output.write_bytes(response.content)
            print(f"Excel de SIMULACIÓN: {args.output}")
        else:
            print(json.dumps(result["diagnostics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
