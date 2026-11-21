import math
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, time
from io import BytesIO
from typing import Protocol
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

import pandas as pd
from openpyxl import load_workbook
from pydantic import ValidationError

from app.models.schemas import Issue, Passenger, PassengerData, ValidationStatus

ALIASES = {
    "name": {"nombre", "chofer", "conductor", "pasajero", "identificador"},
    "address": {"direccion", "domicilio", "ubicacion", "direccion recogida"},
    "commune": {"comuna", "sector"},
    "work_time": {"ingreso", "hora", "turno", "hora entrada", "hora de ingreso"},
    "service_date": {"fecha", "fecha servicio", "fecha del servicio"},
    "latitude": {"latitud", "lat", "latitude"},
    "longitude": {"longitud", "lon", "lng", "longitude"},
}


def normalize(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


class HeaderInterpreter(Protocol):
    """Future LLM adapter: propose mappings for human review, never invent records."""

    def propose(self, rows: list[list]) -> dict[int, str]: ...


def parse_time(value) -> time:
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time) and not value.tzinfo:
        return value.replace(microsecond=0)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value) and 0 <= value < 1:
            seconds = round(value * 86400)
            if seconds < 86400:
                return time(seconds // 3600, seconds // 60 % 60, seconds % 60)
        raise ValueError("Hora numérica ambigua; use HH:MM o una fracción de día Excel")
    text = str(value or "").strip().upper()
    for fmt in ("%H:%M", "%H:%M:%S", "%H.%M", "%I:%M %p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError("Horario ausente o ambiguo; indique HH:MM")


def json_value(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def validate_passengers(passengers: list[Passenger]) -> list[Passenger]:
    groups = defaultdict(list)
    for p in passengers:
        # Recompute business validation, preserving unresolved source problems.
        p.issues = [i for i in p.issues if i.code.startswith("source_")]
        if p.excluded:
            continue
        for field in ("name", "address", "commune", "work_time"):
            if getattr(p, field) is None:
                p.issues.append(Issue(code="required", field=field, message="Campo obligatorio"))
        if p.address and (len(p.address) < 8 or not re.search(r"\d|s/n", p.address.lower())):
            p.issues.append(
                Issue(
                    code="incomplete_address",
                    field="address",
                    message="Revise dirección: se requiere calle y número o s/n explícito",
                )
            )
        if p.latitude is None or p.longitude is None:
            p.issues.append(
                Issue(
                    code="missing_coordinates",
                    field="latitude",
                    severity="warning",
                    message="Faltan coordenadas verificadas; no se puede optimizar este registro",
                )
            )
        key = (
            normalize(p.name),
            normalize(p.address),
            normalize(p.commune),
            p.work_time,
            p.service_date,
        )
        if p.name and p.address and p.work_time:
            groups[key].append(p)
    for group in groups.values():
        if len(group) > 1:
            for p in group:
                p.issues.append(
                    Issue(
                        code="duplicate",
                        message="Posible duplicado; revise los datos o excluya la fila repetida",
                    )
                )
    for p in passengers:
        p.validation_status = (
            ValidationStatus.EXCLUDED
            if p.excluded
            else ValidationStatus.REVIEW
            if p.issues
            else ValidationStatus.VALID
        )
    return passengers


def parse_excel(content: bytes, service_id: str, service_date: date):
    try:
        with ZipFile(BytesIO(content)) as archive:
            if (
                len(archive.infolist()) > 2000
                or sum(i.file_size for i in archive.infolist()) > 50 * 1024 * 1024
            ):
                raise ValueError("XLSX descomprimido excede el límite de 50 MB / 2000 entradas")
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=False)
    except (BadZipFile, KeyError, OSError) as exc:
        raise ValueError("Archivo XLSX inválido") from exc
    passengers = []
    report = {"sheets": [], "ignored_sheets": [], "warnings": []}
    try:
        if len(workbook.worksheets) > 20:
            raise ValueError("Máximo 20 hojas por archivo")
        for sheet in workbook:
            if sheet.max_row > 10001 or sheet.max_column > 100:
                raise ValueError("Máximo 10000 filas y 100 columnas por hoja")
            rows = list(sheet.iter_rows(values_only=True))
            mapping, header_index, ambiguous = {}, None, False
            for index, row in enumerate(rows[:30]):
                candidate = {}
                for col, value in enumerate(row):
                    for field, names in ALIASES.items():
                        if normalize(value) in names:
                            candidate[col] = field
                if len(set(candidate.values()) & {"name", "address", "work_time"}) >= 2:
                    mapping, header_index = candidate, index
                    ambiguous = len(set(candidate.values())) != len(candidate)
                    break
            if header_index is None:
                report["ignored_sheets"].append(sheet.title)
                continue
            report["sheets"].append(
                {
                    "name": sheet.title,
                    "header_row": header_index + 1,
                    "mapping": mapping,
                    "ambiguous": ambiguous,
                }
            )
            frame = pd.DataFrame(rows[header_index + 1 :], dtype=object)
            for offset, row in enumerate(frame.itertuples(index=False, name=None)):
                if all(value is None for value in row):
                    continue
                original = {
                    str(i + 1): {
                        "header": json_value(rows[header_index][i]),
                        "value": json_value(value),
                    }
                    for i, value in enumerate(row)
                }
                values, issues = {"service_date": service_date}, []
                if ambiguous:
                    issues.append(
                        Issue(
                            code="source_ambiguous_headers",
                            message="Encabezados equivalentes repetidos; revise la hoja",
                        )
                    )
                for col, field in mapping.items():
                    value = row[col] if col < len(row) else None
                    if value is None or (isinstance(value, str) and not value.strip()):
                        continue
                    try:
                        if isinstance(value, str) and value.startswith("="):
                            raise ValueError(
                                "Fórmula sin valor confiable; ingrese un valor explícito"
                            )
                        if field == "work_time":
                            values[field] = parse_time(value)
                        elif field == "service_date":
                            parsed = (
                                value.date()
                                if isinstance(value, datetime)
                                else (
                                    value
                                    if isinstance(value, date)
                                    else date.fromisoformat(str(value))
                                )
                            )
                            if parsed != service_date:
                                raise ValueError(
                                    "Fecha de la fila difiere de la fecha del servicio"
                                )
                        elif field in ("latitude", "longitude"):
                            number = float(str(value).replace(",", "."))
                            limit = 90 if field == "latitude" else 180
                            if not math.isfinite(number) or abs(number) > limit:
                                raise ValueError("Coordenada fuera de rango")
                            values[field] = number
                        else:
                            values[field] = str(value).strip()
                    except (ValueError, TypeError) as exc:
                        issues.append(Issue(code="source_invalid", field=field, message=str(exc)))
                try:
                    data = PassengerData(**values)
                except ValidationError as exc:
                    for error in exc.errors():
                        field = str(error["loc"][0])
                        values.pop(field, None)
                        issues.append(
                            Issue(code="source_invalid", field=field, message=error["msg"])
                        )
                    data = PassengerData(**values)
                passengers.append(
                    Passenger(
                        **data.model_dump(),
                        id=str(uuid4()),
                        service_id=service_id,
                        validation_status=ValidationStatus.REVIEW,
                        issues=issues,
                        original_values=original,
                        source_sheet=sheet.title,
                        source_row=header_index + offset + 2,
                    )
                )
                if len(passengers) > 10000:
                    raise ValueError("Máximo 10000 pasajeros por importación")
    finally:
        workbook.close()
    if not passengers:
        raise ValueError("No se encontraron pasajeros con encabezados reconocibles")
    validate_passengers(passengers)
    report["records"] = len(passengers)
    report["pending_review"] = sum(
        p.validation_status == ValidationStatus.REVIEW for p in passengers
    )
    return passengers, report
