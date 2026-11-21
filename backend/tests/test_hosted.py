from io import BytesIO

from app.hosted import create_hosted_app
from fastapi.testclient import TestClient
from openpyxl import load_workbook


def test_hosted_isolated_demo_from_login_to_joint_excel(tmp_path):
    (tmp_path / "index.html").write_text("<html>SPA</html>")
    (tmp_path / "assets").mkdir()
    password = "fictional-32-character-test-password"
    app = create_hosted_app(password, tmp_path)
    with (
        TestClient(app, base_url="https://demo.test") as first,
        TestClient(app, base_url="https://demo.test") as second,
    ):
        assert first.get("/health").json() == {"status": "ok"}
        assert first.get("/planificacion").text == "<html>SPA</html>"
        assert first.get("/assets/missing.js").status_code == 404
        assert first.get("/docs").status_code == 404
        assert first.get("/api/v2/ingestions").status_code == 401
        assert first.post("/api/demo/login", json={"password": "wrong"}).status_code == 401
        assert (
            first.post(
                "/api/demo/login",
                json={"password": password},
                headers={"Sec-Fetch-Site": "cross-site"},
            ).status_code
            == 403
        )
        signed = first.post("/api/demo/login", json={"password": password})
        assert "Secure" in signed.headers["set-cookie"]
        assert "HttpOnly" in signed.headers["set-cookie"]
        assert first.get("/api/docs").status_code == 404
        preparation = first.get("/api/v5/operator/preparation").json()
        assert preparation["locked"] is True
        assert preparation["depot_id"] == "base-demo"
        assert first.put("/api/v5/operator/preparation", json={}).status_code == 404
        assert first.post("/api/v2/terminals", json={}).status_code == 404
        assert first.post("/api/demo/reset", content=b"x" * (512 * 1024 + 1)).status_code == 413
        assert second.post("/api/demo/login", json={"password": password}).status_code == 200

        route = "/api/v5/operator/ingestions/automatic"
        ids, batch_ids = [], []
        for slug, commune in [("gran-america", "Pudahuel"), ("lo-blanco", "Maipú")]:
            fixture = first.get(f"/api/demo/rosters/{slug}")
            assert fixture.status_code == 200
            filename = f"demo-{slug}.xlsx"
            assert filename in fixture.headers["content-disposition"]
            files = {"file": (filename, fixture.content)}
            assert second.post(route, files=files).status_code == 422
            assert (
                first.post(route, files={"file": (filename, fixture.content + b"x")}).status_code
                == 422
            )
            imported = first.post(route, files=files)
            assert imported.status_code == 201, imported.text
            result = imported.json()
            batch_ids.append(result["batch"]["id"])
            assert len(result["requests"]) == 8
            pending = [ride for ride in result["requests"] if ride["validation_status"] != "valid"]
            assert len(pending) == 1
            correction = f"/api/v2/requests/{pending[0]['id']}"
            assert (
                first.patch(
                    correction, json={"changes": {"name": "Arbitrary"}, "reason": "fixture"}
                ).status_code
                == 422
            )
            corrected = first.patch(
                correction, json={"changes": {"commune": commune}, "reason": "fixture"}
            )
            assert corrected.json()["validation_status"] == "valid"
            ids.extend(ride["id"] for ride in result["requests"])
        assert second.get("/api/v2/ingestions").json() == []
        assert second.get(f"/api/v2/ingestions/{batch_ids[0]}").status_code == 404

        reviews = first.post("/api/v5/operator/locations/prepare", json=ids).json()
        assert all(review["status"] == "approved" for review in reviews.values())
        origin = first.get("/api/depots").json()[0]
        vans = [van["id"] for van in first.get("/api/vehicles").json()]
        origins = {van: {k: origin[k] for k in ("latitude", "longitude")} for van in vans}
        matrix = first.post(
            "/api/v4/geo/matrices", json={"request_ids": ids, "vehicle_origins": origins}
        )
        assert matrix.status_code == 201, matrix.text
        result = first.post(
            "/api/v3/plans/preview",
            json={
                "service_date": pending[0]["service_date"],
                "original_batch_ids": batch_ids,
                "request_ids": ids,
                "vehicle_ids": vans,
                "matrix_id": matrix.json()["id"],
                "max_onboard_minutes": 240,
                "boarding_seconds": 0,
                "vehicle_origins": {
                    van: point | {"source": "fixture"} for van, point in origins.items()
                },
            },
        )
        assert result.status_code == 200, result.text
        plan = result.json()
        assert plan["simulation"] is True
        assert plan["rules"] == preparation["rules"]
        assert {trip["customer_id"] for trip in plan["trips"]} == {"gran_america", "lo_blanco"}
        assert all(trip["trip_number"] <= 2 for trip in plan["trips"])
        assert len(plan["unassigned"]) + sum(len(trip["stops"]) for trip in plan["trips"]) == 16
        exported = first.post("/api/v5/operator/plans/export", json=plan)
        assert exported.status_code == 200, exported.text
        sheet = load_workbook(BytesIO(exported.content), read_only=True)["Vista previa"]
        assert sheet["B1"].value == "Simulación"
        assert sheet["L4"].value.startswith("Persona ficticia")

        assert second.post("/api/v5/operator/plans/export", json=plan).status_code == 409
        assert first.post("/api/demo/reset", json={}).status_code == 200
        assert first.get("/api/v2/ingestions").json() == []
