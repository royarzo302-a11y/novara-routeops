from datetime import date, time

import pytest
from app.ingestion.real_excel import IngestionError, normalize_phone, parse_real_excel
from app.models.ingestion import CustomerCode, DocumentRole, Terminal
from app.services.reconciliation import reconcile

from .ingestion_builders import DAY, GA, LB, ga_row, lb_row, workbook


def parse(content, customer="gran_america", role="original", **kwargs):
    return parse_real_excel(
        content, CustomerCode(customer), DocumentRole(role), archive_date=DAY, **kwargs
    )


def terminal(customer="gran_america"):
    return Terminal(id="terminal", customer_id=customer, name="Terminal Sintético")


def test_profile_ga_blocks_master_and_duplicates():
    content = workbook(
        [
            (
                "Base maestra",
                [
                    ["Código", "Nombre completo", "Teléfono", "Fecha contrato"],
                    ["REF-01", "Referencia Sintética", "970000099", DAY],
                ],
            ),
            (
                "Acercamiento",
                [
                    GA,
                    ga_row(),
                    [2],
                    [],
                    GA,
                    ga_row(),
                    [3, None, None, None, '=IFERROR(A1,"")', None, None, None],
                ],
            ),
        ]
    )
    result = parse(content)
    assert len(result.requests) == 2
    assert not any(r.excluded for r in result.requests)
    assert all("duplicate_candidate" in {i.code for i in r.issues} for r in result.requests)
    assert result.batch.sheets[0].category == "reference_master"
    assert result.batch.sheets[1].header_rows == [1, 5]
    assert result.requests[1].provenance.block == 2
    assert result.requests[1].provenance.row == 6
    assert result.requests[0].work_time == time(5)
    assert result.requests[0].phone == "+56970000001"


def test_lo_blanco_and_shifted_empty_template():
    content = workbook(
        [
            ("Acercamiento", [LB, lb_row()]),
            (
                "Base",
                [
                    ["Código", "Nombres y Apellidos", "Dirección", "Comuna", "Teléfono"],
                    ["REF-01", "Referencia Sintética", "Calle Ficticia 201", "Comuna", "970000099"],
                ],
            ),
            ("Plantilla", [[], ["Texto de ejemplo"], [], [], [None, *LB], [None, 1], [None, 2]]),
        ]
    )
    result = parse(content, "lo_blanco", terminal=terminal("lo_blanco"))
    assert len(result.requests) == 1
    request = result.requests[0]
    assert request.customer_id == "lo_blanco"
    assert request.terminal_name == "Terminal Sintético" and request.terminal_id == "terminal"
    assert request.validation_status == "valid"
    assert result.batch.sheets[2].records == 0
    assert result.batch.sheets[2].header_rows == [5]
    assert not any(i.code == "missing_coordinates" for i in request.issues)


def test_annotated_lo_header_is_only_a_reviewable_preview():
    headers = LB.copy()
    headers[2] = "Hora de ingreso (programada)"
    result = parse(
        workbook([("Acercamiento", [headers, lb_row()])]),
        "lo_blanco",
        terminal=terminal("lo_blanco"),
    )
    assert len(result.requests) == 1
    request = result.requests[0]
    assert request.work_time == time(5)
    assert request.validation_status == "pending_review"
    assert "source_header_variant" in {i.code for i in request.issues}


def test_internal_selects_lists_not_routes_or_closures():
    content = workbook(
        [
            ("Acercamiento", [[*GA, "Hora de recogida"], [*ga_row(), "04:20"]]),
            ("Ruta 1", [[*GA, "Hora de recogida"], [*ga_row(), "04:20"]]),
            ("Observaciones", [[*GA, "Hora Llegada Depósito"], [*ga_row(), "04:50"]]),
        ]
    )
    result = parse(content, role="internal")
    assert len(result.requests) == 1
    assert result.requests[0].pickup_time == time(4, 20)
    assert [s.category for s in result.batch.sheets] == [
        "active_roster",
        "route_reference",
        "closure_reference",
    ]


def test_lo_internal_plain_driver_sheet_is_reference():
    content = workbook(
        [
            ("Acercamiento", [LB, lb_row()]),
            ("Etiqueta Sintética", [LB, lb_row()]),
        ]
    )
    result = parse(content, "lo_blanco", "internal")
    assert len(result.requests) == 1
    assert result.batch.sheets[1].category == "route_or_unclassified_reference"


def test_directions_and_dates_not_invented():
    outbound = GA.copy()
    outbound[2] = "Hora Término"
    a, b = ga_row(day=None), ga_row(day=DAY)
    b[2] = "23:30"
    result = parse(
        workbook([("Acercamiento", [GA, a]), ("Término", [outbound, b])]), expected_service_date=DAY
    )
    assert [r.direction for r in result.requests] == ["inbound", "outbound"]
    assert result.requests[0].service_date is None
    assert result.requests[1].work_time is None
    assert result.requests[1].end_time == time(23, 30)
    assert not any(i.code == "duplicate_candidate" for r in result.requests for i in r.issues)


def test_formulas_cached_values_and_volatile_dates():
    row = ga_row()
    row[1], row[4] = "=TODAY()", "=VLOOKUP(D2,'[external.xlsx]Base'!A:B,2,FALSE)"
    content = workbook(
        [("Acercamiento", [GA, row])],
        caches={(1, "B2"): DAY, (1, "E2"): "Persona Sintética Guardada"},
    )
    result = parse(content, expected_service_date=date(2026, 11, 11))
    request = result.requests[0]
    assert request.name == "Persona Sintética Guardada"
    assert request.service_date == DAY
    assert request.validation_status == "pending_review"
    assert {i.code for i in request.issues} >= {
        "source_cached_unverified",
        "source_volatile_formula",
        "source_external_reference",
        "date_context_conflict",
    }
    evidence = next(e for e in request.evidence if e.field == "name")
    assert evidence.raw_value == row[4] and evidence.formula == row[4]
    assert evidence.stored_value == "Persona Sintética Guardada"
    assert evidence.origin == "cached_unverified"


def test_code_without_formula_cache_is_retained():
    row = ga_row()
    row[4], row[5] = "=A99", "=B99"
    result = parse(workbook([("Acercamiento", [GA, row])]))
    assert len(result.requests) == 1
    assert result.requests[0].name is None
    assert "source_formula_without_cache" in {i.code for i in result.requests[0].issues}


def test_invalid_cells_keep_rest_and_do_not_echo_values():
    row = ga_row()
    row[2], row[7] = "4 o 5", "TELÉFONO SINTÉTICO INVÁLIDO"
    result = parse(workbook([("Acercamiento", [GA, row])]))
    request = result.requests[0]
    assert request.employee_code == "SIM-001"
    assert request.work_time is None and request.phone is None
    assert row[7] not in str(request.issues)
    assert next(e for e in request.evidence if e.field == "phone").raw_value == row[7]


def test_conflicting_columns_are_not_overwritten():
    result = parse(
        workbook([("Acercamiento", [[*GA, "Domicilio"], [*ga_row(), "Otra Calle Ficticia 999"]])])
    )
    request = result.requests[0]
    assert request.address is None
    assert len([e for e in request.evidence if e.field == "address"]) == 2
    assert "source_ambiguous_columns" in {i.code for i in request.issues}


def test_mixed_dates_and_terminal_conflict_are_pending():
    a, b = lb_row(), lb_row("SIM-002")
    b[1] = date(2026, 11, 11)
    a[0] = "Otro Terminal Sintético"
    result = parse(
        workbook([("Acercamiento", [LB, a, b])]), "lo_blanco", terminal=terminal("lo_blanco")
    )
    assert all("mixed_dates" in {i.code for i in r.issues} for r in result.requests)
    assert result.requests[0].terminal_id is None
    assert result.requests[1].terminal_id == "terminal"


@pytest.mark.parametrize("content", [b"", b"not an xlsx"])
def test_bad_workbook_safe_error(content):
    with pytest.raises(IngestionError, match="segura"):
        parse(content)


def test_reconcile_keeps_dates_and_duplicate_ambiguity():
    original = parse(workbook([("Acercamiento", [GA, ga_row(), ga_row()])]))
    internal = parse(workbook([("Acercamiento", [GA, ga_row()])]), role="internal")
    result = reconcile(original, internal)
    assert len(result.ambiguous_groups) == 1
    assert result.matches == []
    assert len(result.ambiguous_groups[0]["original_ids"]) == 2
    assert not any(r.excluded for r in original.requests)


def test_reconcile_field_changes_missing_and_extra_without_pii():
    original = parse(workbook([("Acercamiento", [GA, ga_row(), ga_row("SIM-002")])]))
    row = ga_row(day=date(2026, 11, 11))
    row[5] = "Calle Corregida Sintética 987"
    internal = parse(workbook([("Acercamiento", [GA, row, ga_row("SIM-003")])]), role="internal")
    result = reconcile(original, internal)
    assert result.difference_counts == {"address": 1, "service_date": 1}
    assert (
        len(result.matches)
        == len(result.unmatched_original_ids)
        == len(result.unmatched_internal_ids)
        == 1
    )
    assert "Calle Corregida" not in result.model_dump_json()
    assert "SIM-001" not in result.model_dump_json()


def test_fallback_identity_is_provisional():
    row = ga_row(code=None)
    a = parse(workbook([("Acercamiento", [GA, row])]))
    b = parse(workbook([("Acercamiento", [GA, row])]), role="internal")
    report = reconcile(a, b)
    assert report.matches[0].provisional
    assert report.status == "pending_review"


def test_reconciliation_scope_and_terminal_customer():
    a = parse(workbook([("Acercamiento", [GA, ga_row()])]))
    b = parse(workbook([("Acercamiento", [LB, lb_row()])]), "lo_blanco", "internal")
    with pytest.raises(ValueError, match="clientes"):
        reconcile(a, b)
    with pytest.raises(IngestionError, match="otro cliente"):
        parse(workbook([("Acercamiento", [GA, ga_row()])]), terminal=terminal("lo_blanco"))


@pytest.mark.parametrize("value", ["9 faltan dígitos", "123", "+56970000001ABC", 4.2, True])
def test_phone_does_not_invent_missing_digits(value):
    with pytest.raises(ValueError):
        normalize_phone(value)
