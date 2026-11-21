"""Synthetic API for the browser test. All state is held in an isolated in-memory database."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from io import BytesIO
from random import Random, SystemRandom
from zoneinfo import ZoneInfo

from app.api.geospatial import GeoAccess
from app.geo.models import Candidate
from app.geo.providers import (
    SyntheticGeocodingProvider,
    SyntheticRoadProvider,
)
from app.geo.service import GeoSettings
from app.main import create_app
from app.models.ingestion import CustomerCode
from fastapi import Response
from openpyxl import Workbook

from scripts.demo_data import STOPS, TERMINALS, demo_points, road_demo, seed_resources

ready_demo = os.getenv("NOVARA_PRESET_DEMO") == "1"
HISTORICAL_WEIGHTS = {
    "Pudahuel": 22,
    "Maipú": 16,
    "Lo Prado": 12,
    "Renca": 10,
    "Independencia": 9,
    "Quinta Normal": 8,
    "Cerro Navia": 5,
    "Quilicura": 4,
    "Cerrillos": 3,
    "Estación Central": 3,
}
SHIFT_WEIGHTS = {
    CustomerCode.GRAN_AMERICA: (
        ("04:00", "04:30", "05:00", "05:30", "06:00", "06:30"),
        (16, 10, 47, 16, 16, 14),
    ),
    CustomerCode.LO_BLANCO: (("05:00", "06:00"), (8, 4)),
}
app = create_app(
    "sqlite:///:memory:",
    geo_settings=GeoSettings(
        token=os.environ["NOVARA_BROWSER_TEST_TOKEN"],
        geocoder=SyntheticGeocodingProvider(
            demo_points
            if ready_demo
            else {
                "calle ficticia 101": [
                    Candidate(id="fixture-1", latitude=-33.42, longitude=-70.59, context_match=True)
                ]
            }
        ),
        road=road_demo() if ready_demo else SyntheticRoadProvider(),
        allow_simulation=True,
        demo_mode=ready_demo,
    ),
)


def demo_roster_data(seed: int | None):
    random = Random(seed) if seed is not None else SystemRandom()
    if seed == 0:  # Stable reference for browser regression tests.
        return CustomerCode.GRAN_AMERICA, (0, 4, 2, 6, 1, 3, 5, 7), ["04:30"] * 4 + ["06:30"] * 4, 1
    customer = random.choice(list(CustomerCode))
    count = random.randint(8, 15) if customer == CustomerCode.GRAN_AMERICA else random.randint(6, 9)
    remaining = [
        [i for i, stop in enumerate(STOPS) if stop[2] == commune] for commune in HISTORICAL_WEIGHTS
    ]
    selected = []
    for _ in range(min(count, 5)):
        groups = random.choices(
            remaining, weights=[HISTORICAL_WEIGHTS[STOPS[g[0]][2]] for g in remaining]
        )
        group = groups[0]
        selected.append(random.choice(group))
        remaining.remove(group)
    available = [i for i in range(len(STOPS)) if i not in selected and STOPS[i][2] != "Santiago"]
    available.extend(random.sample([i for i, stop in enumerate(STOPS) if stop[2] == "Santiago"], 3))
    selected.extend(random.sample(available, count - len(selected)))
    random.shuffle(selected)
    slots, weights = SHIFT_WEIGHTS[customer]
    shift_times = random.choices(slots, weights=weights, k=count)
    return customer, selected, shift_times, random.randint(1, 14)


def sample_xlsx(seed: int | None = None) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Acercamiento"
    customer, stop_indexes, shift_times, offset = demo_roster_data(seed)
    headers = ["Fecha", "Hora Inicio", "Código", "Nombres", "Dirección", "Comuna", "Teléfono"]
    if customer == CustomerCode.LO_BLANCO:
        headers[:2] = ["Fecha de presentación", "Hora de ingreso"]
        headers.append("Depósito asignado")
    sheet.append(headers)
    service_date = datetime.now(ZoneInfo("America/Santiago")).date() + timedelta(days=offset)
    for index, (stop_index, work_time) in enumerate(zip(stop_indexes, shift_times, strict=True), 1):
        _, address, commune, _, _ = STOPS[stop_index]
        sheet.append(
            [
                service_date,
                work_time,
                f"NOVARA-DEMO-{index:02}",
                f"Pasajero de prueba {index}",
                address,
                commune,
                f"9700000{index:02}",
            ]
            + ([TERMINALS[customer][0]] if customer == CustomerCode.LO_BLANCO else [])
        )
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def configure_demo():
    startup = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        async with startup(instance):
            with instance.state.sessions() as db:
                seed_resources(db)
            yield

    app.router.lifespan_context = lifespan

    @app.get("/v5/operator/demo/roster")
    def demo_roster(access: GeoAccess, seed: int | None = None):
        return Response(
            sample_xlsx(seed),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Cache-Control": "no-store"},
        )


if ready_demo:
    configure_demo()
