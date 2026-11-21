from datetime import datetime, time
from io import BytesIO

import pytest
from app.ingestion.excel import normalize, parse_excel, parse_time
from openpyxl import Workbook

from .conftest import DATA, DAY


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("04:00", time(4)),
        ("5:30", time(5, 30)),
        ("05.30", time(5, 30)),
        ("05:30 AM", time(5, 30)),
        (5.5 / 24, time(5, 30)),
        (time(6), time(6)),
        (datetime(2026, 1, 1, 4), time(4)),
        (0, time(0)),
    ],
)
def test_time_formats(value, expected):
    assert parse_time(value) == expected


@pytest.mark.parametrize("value", ["4", "4 o 5", "25:00", "", None, 4, 530, True, 1, float("nan")])
def test_ambiguous_times(value):
    with pytest.raises(ValueError):
        parse_time(value)


def test_headers():
    assert normalize("  DIRECCIÓN  ") == "direccion"
    assert normalize("Hora_entrada") == "hora entrada"


@pytest.mark.parametrize("filename", ["case_a_structured.xlsx", "case_b_messy.xlsx"])
def test_variable_structure(filename):
    passengers, report = parse_excel((DATA / filename).read_bytes(), "s", DAY)
    assert len(passengers) == 14
    assert all(p.validation_status == "valid" for p in passengers)
    assert report["ignored_sheets"] == ["Instrucciones"]
    assert passengers[0].original_values
    assert passengers[0].work_time == time(4)


def test_errors_and_duplicates():
    passengers, report = parse_excel((DATA / "case_c_errors.xlsx").read_bytes(), "s", DAY)
    codes = [issue.code for p in passengers for issue in p.issues]
    assert {
        "incomplete_address",
        "source_invalid",
        "required",
        "missing_coordinates",
        "duplicate",
    } <= set(codes)
    assert codes.count("duplicate") == 2
    assert report["pending_review"] == 6
    assert passengers[1].work_time is None
    assert "4 o 5" in str(passengers[1].original_values)


def workbook_bytes(rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_missing_columns():
    passengers, _ = parse_excel(
        workbook_bytes(
            [
                ["Nombre", "Dirección"],
                ["Persona sintética", "Calle Simulada 100"],
            ]
        ),
        "s",
        DAY,
    )
    assert {i.field for i in passengers[0].issues} >= {"commune", "work_time", "latitude"}


def test_formula_date_and_duplicate_headers():
    passengers, report = parse_excel(
        workbook_bytes(
            [
                ["Nombre", "Chofer", "Dirección", "Hora", "Fecha"],
                ["Persona A", "Persona B", "=A1", "04:00", "2026-11-21"],
            ]
        ),
        "s",
        DAY,
    )
    assert report["sheets"][0]["ambiguous"]
    p = passengers[0]
    assert p.address is None
    assert p.service_date == DAY
    assert {i.code for i in p.issues} >= {"source_ambiguous_headers", "source_invalid"}


def test_unknown_structure():
    with pytest.raises(ValueError, match="encabezados"):
        parse_excel(workbook_bytes([["Desconocido"], ["Datos"]]), "s", DAY)


def test_invalid_file():
    with pytest.raises(ValueError, match="inválido"):
        parse_excel(b"not an xlsx", "s", DAY)
