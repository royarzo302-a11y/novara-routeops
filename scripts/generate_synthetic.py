"""Regenerate fictitious workbooks without personal data: python scripts/generate_synthetic.py."""

import json
from datetime import date, time
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1] / "data" / "synthetic"
SERVICE_DATE = date(2026, 11, 20)
HEADERS = ["Nombre", "Dirección", "Comuna", "Ingreso", "Fecha", "Latitud", "Longitud"]
COMMUNES = ["Santiago", "San Miguel", "La Cisterna", "San Joaquín"]


def records(count=14):
    rows = []
    for i in range(count):
        hour = time(4) if i < 4 else time(5) if i < 8 else time(5, 30) if i < 11 else time(6)
        rows.append(
            [
                f"Pasajero sintético {i + 1:02}",
                f"Calle Simulada {101 + i}",
                COMMUNES[i % 4],
                hour,
                SERVICE_DATE,
                -33.45 - (i % 4) * 0.008,
                -70.65 - (i % 3) * 0.008,
            ]
        )
    return rows


def write(name, rows, headers=HEADERS, preamble=False):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Pasajeros"
    if preamble:
        sheet.append(["DATOS SINTÉTICOS — EJEMPLO NO OPERATIVO"])
        sheet.append([])
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    info = workbook.create_sheet("Instrucciones")
    info.append(["Datos ficticios, coordenadas ilustrativas. No corresponde a personas reales."])
    workbook.save(ROOT / name)


def generate():
    ROOT.mkdir(parents=True, exist_ok=True)
    write("case_a_structured.xlsx", records())
    messy = []
    for i, row in enumerate(records()):
        hour = row[3]
        formats = [
            hour.strftime("%H:%M"),
            hour.strftime("%H.%M"),
            (hour.hour * 60 + hour.minute) / 1440,
            hour.strftime("%I:%M %p"),
        ]
        messy.append([row[2], formats[i % 4], row[0], row[1], row[6], row[5], row[4]])
    write(
        "case_b_messy.xlsx",
        messy,
        [" SECTOR ", "Hora entrada", "Chofer", "Domicilio", "Lon", "Lat", "Fecha servicio"],
        preamble=True,
    )
    errors = records(6)
    errors[0][1] = "Sin número"
    errors[1][3] = "4 o 5"
    errors[2][0] = None
    errors[3][5] = None
    errors[4] = errors[5].copy()
    write("case_c_errors.xlsx", errors)
    feasible = records(6)
    for row in feasible:
        row[3] = time(5)
    write("case_d_feasible.xlsx", feasible)
    write("case_e_infeasible.xlsx", feasible)
    (ROOT / "scenarios.json").write_text(
        json.dumps(
            {
                "simulation": True,
                "service_date": SERVICE_DATE.isoformat(),
                "depot": {
                    "name": "Depósito sintético Gran América",
                    "address": "Calle Simulada 1000",
                    "latitude": -33.45,
                    "longitude": -70.65,
                },
                "fleet": {
                    "vans": 3,
                    "capacity_each": 6,
                    "driver_start": "00:00",
                    "driver_end": "08:00",
                },
                "cases": {
                    "A": {"file": "case_a_structured.xlsx", "config": {}},
                    "B": {"file": "case_b_messy.xlsx", "config": {}},
                    "C": {"file": "case_c_errors.xlsx", "expected": "needs_review"},
                    "D": {"file": "case_d_feasible.xlsx", "config": {}, "expected": "feasible"},
                    "E": {
                        "file": "case_e_infeasible.xlsx",
                        "config": {"max_onboard_minutes": 1},
                        "expected": "infeasible",
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    generate()
