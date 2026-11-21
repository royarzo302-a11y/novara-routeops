from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.models.schemas import OptimizationResult


def safe_text(value):
    # User-originated text must never become an Excel formula.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_routes(result: OptimizationResult) -> bytes:
    if result.status != "feasible" or result.stale:
        raise ValueError("Solo se exportan simulaciones factibles y vigentes")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Rutas SIMULADAS"
    sheet.append(["SIMULACIÓN — NO UTILIZAR PARA OPERACIÓN REAL"])
    sheet.append(["Tiempos y distancias sintéticos; no representan tráfico real."])
    headers = [
        "Fecha servicio",
        "Ruta",
        "Vehículo",
        "Conductor",
        "Viaje",
        "Orden",
        "Pasajero",
        "Dirección",
        "Comuna",
        "Recogida estimada local",
        "Ingreso local",
        "Llegada estimada local",
        "A bordo (min)",
        "Duración ruta (min)",
        "Distancia simulada (km)",
        "Alertas / observaciones",
    ]
    sheet.append(headers)
    for route in result.routes:
        for stop in route.stops:
            sheet.append(
                [
                    safe_text(value)
                    for value in [
                        route.service_date.isoformat(),
                        route.id,
                        route.vehicle_identifier,
                        route.driver_identifier,
                        route.trip_number,
                        stop.order,
                        stop.name,
                        stop.address,
                        stop.commune,
                        stop.pickup_at.isoformat(sep=" "),
                        stop.work_time.isoformat(),
                        route.arrival_at.isoformat(sep=" "),
                        round(stop.onboard_seconds / 60, 2),
                        round(route.duration_seconds / 60, 2),
                        round(route.distance_meters / 1000, 3),
                        "; ".join(route.observations),
                    ]
                ]
            )
    sheet.freeze_panes = "A4"
    sheet.auto_filter.ref = f"A3:P{sheet.max_row}"
    for cell in sheet[3]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="203864")
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = min(
            60,
            max(15, max(len(str(c.value or "")) for c in column) + 2),
        )
    metadata = workbook.create_sheet("Supuestos")
    for line in result.limitations:
        metadata.append([safe_text(line)])
    metadata.append(["Parámetros", result.config.model_dump_json()])
    metadata.append(["Datos no calculados", "Tráfico real, geocodificación y segundo viaje"])
    metadata.column_dimensions["A"].width = 110
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def export_joint_preview(plan, *, requests, vehicles, drivers, terminals, customers):
    """Serialize exactly the displayed preview, without creating a second plan."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Vista previa"
    sheet.append(
        [
            "Vista previa enviada por el operador",
            "Simulación"
            if plan.simulation
            else "Estimación vial"
            if plan.matrix_mode == "static_road"
            else "Matriz aportada",
        ]
    )
    sheet.append(["Fecha", plan.service_date.isoformat(), "Fuente", safe_text(plan.matrix_source)])
    sheet.append(
        [
            "Van",
            "Conductor",
            "Cliente",
            "Viaje",
            "Terminal",
            "Orden",
            "Solicitud",
            "Recogida estimada",
            "Llegada estimada",
            "Duración viaje (s)",
            "A bordo (s)",
            "Pasajero",
            "Código de trabajador",
            "Dirección",
            "Comuna",
            "Salida estimada",
            "ID van",
            "ID conductor",
            "ID cliente",
            "ID terminal",
        ]
    )
    for trip in plan.trips:
        for stop in trip.stops:
            request = requests.get(stop.request_id, {})
            sheet.append(
                [
                    safe_text(value)
                    for value in [
                        vehicles.get(trip.vehicle_id, {}).get("identifier", trip.vehicle_id),
                        drivers.get(trip.driver_id, {}).get("identifier", trip.driver_id),
                        customers.get(trip.customer_id, trip.customer_id),
                        trip.trip_number,
                        terminals.get(trip.terminal_id, {}).get("name", trip.terminal_id),
                        stop.sequence,
                        stop.request_id,
                        stop.pickup_at.isoformat(),
                        trip.arrival_at.isoformat(),
                        trip.duration_seconds,
                        stop.onboard_seconds,
                        request.get("name"),
                        request.get("employee_code"),
                        request.get("address"),
                        request.get("commune"),
                        trip.dispatch_at.isoformat(),
                        trip.vehicle_id,
                        trip.driver_id,
                        trip.customer_id,
                        trip.terminal_id,
                    ]
                ]
            )
    sheet.freeze_panes = "A4"
    pending = workbook.create_sheet("Sin asignar")
    pending.append(["Solicitud", "Motivo", "Pasajero", "Código de trabajador"])
    for row in plan.unassigned:
        request = requests.get(row.request_id, {})
        pending.append(
            [
                safe_text(value)
                for value in (
                    row.request_id,
                    row.reason,
                    request.get("name"),
                    request.get("employee_code"),
                )
            ]
        )
    assumptions = workbook.create_sheet("Supuestos")
    assumptions.append(["Matriz", safe_text(plan.matrix_id)])
    assumptions.append(["Fuente vial", safe_text(plan.matrix_source)])
    assumptions.append(
        [
            "Verificación vial",
            plan.matrix_verified_at.isoformat() if plan.matrix_verified_at else None,
        ]
    )
    assumptions.append(["Modelo", safe_text(plan.matrix_mode)])
    assumptions.append(["Tráfico en vivo", "No incorporado"])
    if plan.rules:
        for key, value in plan.rules.model_dump().items():
            assumptions.append([key, value])
    assumptions.column_dimensions["A"].width = 32
    assumptions.column_dimensions["B"].width = 75
    for column, width in {
        "A": 16,
        "B": 21,
        "C": 19,
        "E": 26,
        "G": 21,
        "H": 29,
        "I": 29,
        "L": 24,
        "M": 20,
        "N": 30,
        "O": 18,
        "P": 29,
    }.items():
        sheet.column_dimensions[column].width = width
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
