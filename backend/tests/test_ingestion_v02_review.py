from datetime import date, datetime

from app.ingestion.real_excel import parse_real_excel
from app.models.ingestion import CustomerCode, DocumentRole

from .ingestion_builders import DAY, GA, ga_row, workbook


def test_unknown_identity_table_is_quarantined_not_a_ride():
    content = workbook(
        [
            (
                "Referencia sin horario",
                [
                    [],
                    [None, "Código", "Etiqueta nominal"],
                    [None, "SIM-Q1", "Persona Sintética Uno"],
                    [None, "SIM-Q2", "Persona Sintética Dos"],
                ],
            )
        ]
    )
    result = parse_real_excel(content, CustomerCode.GRAN_AMERICA, DocumentRole.ORIGINAL)
    assert not result.requests
    assert result.batch.status == "pending_review"
    assert result.batch.unclassified_rows == 2
    assert len(result.unclassified_rows) == 2
    row = result.unclassified_rows[0]
    assert row.provenance.row == 3 and row.provenance.header_row == 2
    assert row.cells[0].field == "employee_code" and row.cells[0].raw_value == "SIM-Q1"
    assert row.cells[1].field is None and row.cells[1].raw_value == "Persona Sintética Uno"
    assert row.validation_status == "pending_review"


def test_unknown_rows_persist_but_aggregate_summary_does_not_expose_them(client):
    content = workbook(
        [
            (
                "Sin horario",
                [["Código", "Etiqueta nominal"], ["SIM-Q1", "Persona Sintética Reservada"]],
            )
        ]
    )
    response = client.post(
        "/v2/ingestions",
        data={
            "customer_id": "gran_america",
            "role": "original",
        },
        files={"file": ("synthetic.xlsx", content)},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["batch"]["unclassified_rows"] == 1
    assert client.get(f"/v2/ingestions/{data['batch']['id']}").json() == data
    summary = client.get(f"/v2/ingestions/{data['batch']['id']}/summary").text
    assert "Persona Sintética Reservada" not in summary and "SIM-Q1" not in summary


def test_clock_date_component_is_not_silently_discarded():
    row = ga_row()
    row[2] = datetime(2026, 11, 10, 5)
    result = parse_real_excel(workbook([("Acercamiento", [GA, row])]), "gran_america", "original")
    assert "source_clock_date_component" in {i.code for i in result.requests[0].issues}
    row[2] = datetime(1955, 1, 6, 0)
    result = parse_real_excel(workbook([("Acercamiento", [GA, row])]), "gran_america", "original")
    assert result.requests[0].work_time is None


def test_same_worker_different_date_not_automatically_duplicate():
    content = workbook([("Acercamiento", [GA, ga_row(), ga_row(day=date(2026, 11, 11))])])
    result = parse_real_excel(content, "gran_america", "original")
    assert len(result.requests) == 2
    assert not any(i.code == "duplicate_candidate" for r in result.requests for i in r.issues)
    assert all(i.code != "missing_coordinates" for r in result.requests for i in r.issues)
    assert result.requests[0].service_date == DAY


def test_source_legacy_tables_are_preserved_when_v02_tables_are_added(tmp_path):
    from app.database import database
    from app.main import create_app
    from app.models.entities import Base, DepotRow
    from fastapi.testclient import TestClient

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine, sessions = database(url)
    Base.metadata.create_all(engine, tables=[DepotRow.__table__])
    payload = {
        "id": "legacy-depot",
        "name": "Depósito Sintético Anterior",
        "address": "Calle Ficticia 100",
        "latitude": -33.45,
        "longitude": -70.65,
    }
    with sessions() as db:
        db.add(DepotRow(id="legacy-depot", payload=payload))
        db.commit()
    engine.dispose()
    with TestClient(create_app(url)) as api:
        assert api.get("/depots").json() == [payload]
        assert len(api.get("/v2/customers").json()) == 2


def test_scheduled_row_without_identity_is_preserved_for_review():
    content = workbook([("Acercamiento", [GA, [1, DAY, "05:00", None, "=A99", "=B99"]])])
    result = parse_real_excel(content, "gran_america", "original")
    assert result.requests == []
    assert len(result.unclassified_rows) == 1
    assert result.unclassified_rows[0].provenance.row == 2
    assert any(c.formula for c in result.unclassified_rows[0].cells)


def test_response_validation_cannot_echo_private_values(client):
    marker = "VALOR_PRIVADO_SINTETICO"

    @client.app.get("/v2/_synthetic_invalid_response", response_model=int)
    def synthetic_error():
        return {"name": marker}

    response = client.get("/v2/_synthetic_invalid_response")
    assert response.status_code == 500
    assert marker not in response.text
