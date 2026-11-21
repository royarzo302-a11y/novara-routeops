from app.main import create_app
from fastapi.testclient import TestClient

from .ingestion_builders import DAY, GA, ga_row, workbook


def upload(client, role="original", content=None, customer="gran_america", **extra):
    return client.post(
        "/v2/ingestions",
        data={
            "customer_id": customer,
            "role": role,
            "archive_date": DAY.isoformat(),
            **extra,
        },
        files={"file": ("synthetic.xlsx", content or workbook([("Acercamiento", [GA, ga_row()])]))},
    )


def create_terminal(client, customer="gran_america"):
    response = client.post(
        "/v2/terminals",
        json={
            "customer_id": customer,
            "name": "Terminal Sintético",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_customers_terminals_and_ingestion_are_separate_from_solver(client):
    assert {c["id"] for c in client.get("/v2/customers").json()} == {"gran_america", "lo_blanco"}
    terminal = create_terminal(client)
    result = upload(client, terminal_id=terminal["id"])
    assert result.status_code == 201, result.text
    data = result.json()
    assert data["batch"]["status"] == "interpreted"
    assert data["batch"]["terminal_context_id"] == terminal["id"]
    assert data["requests"][0]["provenance"]["terminal_origin"] == "context"
    assert len(client.get("/v2/terminals?customer_id=gran_america").json()) == 1
    assert client.get("/v2/terminals?customer_id=lo_blanco").json() == []
    assert client.get("/services").json() == []
    assert client.get("/v2/ingestions").json() == [data["batch"]]
    assert client.get(f"/v2/ingestions/{data['batch']['id']}").json() == data
    summary = client.get(f"/v2/ingestions/{data['batch']['id']}/summary").text
    assert "Persona Sintética" not in summary and "Calle Ficticia" not in summary
    assert "SIM-001" not in summary and "970000001" not in summary


def test_correction_trail_keeps_evidence_and_stales_reports(client):
    terminal = create_terminal(client)
    original = upload(client, terminal_id=terminal["id"]).json()
    internal = upload(client, role="internal", terminal_id=terminal["id"]).json()
    response = client.post(
        "/v2/reconciliations",
        json={
            "original_batch_id": original["batch"]["id"],
            "internal_batch_id": internal["batch"]["id"],
        },
    )
    assert response.status_code == 201
    report = response.json()
    assert report["status"] == "reconciled"
    request = original["requests"][0]
    response = client.patch(
        f"/v2/requests/{request['id']}",
        json={
            "changes": {"address": "Calle Corregida Sintética 999"},
            "reason": "Revisión sintética",
        },
    )
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["evidence"] == request["evidence"]
    assert changed["corrections"][0]["previous_values"]["address"] == "Calle Ficticia 101"
    assert changed["corrections"][0]["changes"]["address"] == changed["address"]
    assert client.get(f"/v2/reconciliations/{report['id']}").json()["stale"]


def test_confirmation_is_explicit_and_cannot_fill_missing_values(client):
    row = ga_row()
    row[4] = "=A99"
    terminal = create_terminal(client)
    data = upload(
        client, content=workbook([("Acercamiento", [GA, row])]), terminal_id=terminal["id"]
    ).json()
    request = data["requests"][0]
    response = client.patch(
        f"/v2/requests/{request['id']}",
        json={
            "confirm_fields": ["name"],
            "reason": "Revisión sintética",
        },
    )
    assert response.status_code == 200
    assert response.json()["validation_status"] == "pending_review"
    assert response.json()["name"] is None
    response = client.patch(
        f"/v2/requests/{request['id']}",
        json={
            "changes": {"name": "Persona Sintética Revisada"},
            "reason": "Revisión explícita",
        },
    )
    assert response.status_code == 200
    assert response.json()["validation_status"] == "valid"
    assert len(response.json()["corrections"]) == 2
    assert next(e for e in response.json()["evidence"] if e["field"] == "name")["formula"] == "=A99"


def test_duplicates_require_human_exclusion_or_correction(client):
    terminal = create_terminal(client)
    result = upload(
        client,
        content=workbook([("Acercamiento", [GA, ga_row(), ga_row()])]),
        terminal_id=terminal["id"],
    ).json()
    assert len(result["requests"]) == 2
    response = client.patch(
        f"/v2/requests/{result['requests'][0]['id']}",
        json={
            "changes": {"excluded": True},
            "reason": "Duplicado confirmado por operador sintético",
        },
    )
    assert response.status_code == 200
    updated = client.get(f"/v2/ingestions/{result['batch']['id']}").json()
    assert len(updated["requests"]) == 2
    assert updated["batch"]["excluded"] == 1
    assert updated["batch"]["pending_review"] == 0
    active = next(r for r in updated["requests"] if not r["excluded"])
    assert active["validation_status"] == "valid"


def test_private_values_do_not_appear_in_validation_errors(client):
    marker = "DATO_PRIVADO_SINTETICO_NO_REPETIR"
    response = client.post("/v2/terminals", json={"customer_id": marker, "name": marker})
    assert response.status_code == 422 and marker not in response.text
    data = upload(client).json()
    request_id = data["requests"][0]["id"]
    for body in [
        {"changes": {"work_time": marker}, "reason": "Revisión"},
        {"changes": {"phone": marker}, "reason": "Revisión"},
        {"changes": {}, "reason": "Revisión"},
    ]:
        response = client.patch(f"/v2/requests/{request_id}", json=body)
        assert response.status_code == 422 and marker not in response.text
    assert client.get("/v2/ingestions/missing").status_code == 404
    assert (
        client.post(
            "/v2/ingestions",
            data={"role": "original", "customer_id": "gran_america"},
            files={"file": ("x.xlsx", b"broken")},
        ).status_code
        == 422
    )


def test_cross_customer_terminal_and_reconciliation_scope(client):
    terminal = create_terminal(client, "lo_blanco")
    assert upload(client, terminal_id=terminal["id"]).status_code == 422
    a = upload(client).json()
    b = upload(client, role="internal", archive_date="2026-11-11").json()
    assert (
        client.post(
            "/v2/reconciliations",
            json={
                "original_batch_id": a["batch"]["id"],
                "internal_batch_id": b["batch"]["id"],
            },
        ).status_code
        == 422
    )


def test_corrections_survive_restart_and_old_schema_still_works(tmp_path):
    url = f"sqlite:///{tmp_path / 'private-synthetic.db'}"
    with TestClient(create_app(url)) as api:
        data = upload(api).json()
        request_id = data["requests"][0]["id"]
        response = api.patch(
            f"/v2/requests/{request_id}",
            json={
                "changes": {"employee_code": "SIM-CORRECTED", "work_time": "05:30"},
                "reason": "Corrección sintética",
            },
        )
        assert response.status_code == 200
    with TestClient(create_app(url)) as api:
        request = api.get(f"/v2/requests/{request_id}").json()
        assert request["employee_code"] == "SIM-CORRECTED" and request["work_time"] == "05:30:00"
        assert request["corrections"][0]["previous_values"]["work_time"] == "05:00:00"
        assert len(api.get("/v2/customers").json()) == 2
        assert api.get("/health").status_code == 200
