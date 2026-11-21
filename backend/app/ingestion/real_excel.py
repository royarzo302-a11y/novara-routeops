"""v0.2 ingestion. No evaluation, network, database writes or logging of workbook values."""

import hashlib
import math
import re
import warnings
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from pydantic import TypeAdapter, ValidationError

from app.ingestion.excel import json_value, normalize, parse_time
from app.ingestion.profiles import get_profile
from app.models.ingestion import (
    CellEvidence,
    CustomerCode,
    Direction,
    DocumentRole,
    IngestionBatch,
    IngestionResult,
    Provenance,
    RequestData,
    SheetReport,
    Terminal,
    TransportRequest,
    UnclassifiedRow,
)
from app.models.schemas import Issue, Text, ValidationStatus

EXCEL_ERRORS = {"#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!"}
PLACEHOLDERS = {
    "",
    "0",
    "sin datos",
    "sin informacion",
    "no encontrado",
    "no existe",
    "no disponible",
    "no hay",
    "n a",
    "ref",
    "value",
    "sin personal",
}
TEXT = TypeAdapter(Text)
TIME_FIELDS = {"work_time", "end_time", "pickup_time", "arrival_time"}


class IngestionError(ValueError):
    """Messages are fixed and safe to expose. Never wrap a source value into a message."""


def employee_identity(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)) and float(value).is_integer():
            return str(int(value)) if value else ""
    # Keep meaningful leading zeros in textual codes: do not silently merge distinct codes.
    return normalize(value).replace(" ", "")


def normalize_phone(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)) or not float(value).is_integer():
            raise ValueError("Invalid phone")
        value = str(int(value))
    text = str(value).strip()
    if not re.fullmatch(r"\+?[\d ().-]+", text):
        raise ValueError("Invalid phone")
    digits = re.sub(r"\D", "", text)
    if len(digits) == 9:
        return "+56" + digits
    if len(digits) == 11 and digits.startswith("56"):
        return "+" + digits
    raise ValueError("Invalid phone")


def meaningful(value):
    return value is not None and normalize(value) not in PLACEHOLDERS and value not in EXCEL_ERRORS


def convert(field, value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str) and value in EXCEL_ERRORS:
        raise ValueError("Excel error")
    if field in {"name", "address", "commune", "terminal_name"} and not meaningful(value):
        return None
    if field in TIME_FIELDS:
        if isinstance(value, datetime) and value.year < 2000 and value.date() != date(1900, 1, 1):
            raise ValueError("Ambiguous clock date")
        return parse_time(value)
    if field == "service_date":
        if isinstance(value, datetime):
            value = value.date()
        elif isinstance(value, str):
            value = value.strip()
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
                try:
                    value = datetime.strptime(value, fmt).date()
                    break
                except ValueError:
                    continue
        if not isinstance(value, date) or not 2000 <= value.year <= 2100:
            raise ValueError("Invalid service date")
        return value
    if field == "employee_code":
        if isinstance(value, bool):
            raise ValueError("Invalid code")
        if isinstance(value, (int, float)):
            if not math.isfinite(float(value)) or not float(value).is_integer():
                raise ValueError("Invalid code")
            value = str(int(value))
        if not meaningful(value):
            return None
    if field == "phone":
        return normalize_phone(value)
    return TEXT.validate_python(str(value))


def validate_requests(requests, expected_service_date=None):
    duplicate_groups = defaultdict(list)
    date_groups = defaultdict(set)
    for request in requests:
        # Original evidence is immutable; only human decisions can resolve source findings.
        resolved = {key for c in request.corrections for key in c.changes} | {
            str(key) for c in request.corrections for key in c.confirmed_fields
        }
        request.issues = [
            i for i in request.issues if i.code.startswith("source_") and i.field not in resolved
        ]
        if request.excluded:
            request.validation_status = ValidationStatus.EXCLUDED
            continue
        required = ["employee_code", "name", "address", "commune", "service_date"]
        if request.direction == Direction.INBOUND:
            required.append("work_time")
        elif request.direction == Direction.OUTBOUND:
            required.append("end_time")
        else:
            request.issues.append(
                Issue(
                    code="direction_unknown",
                    field="direction",
                    message="Seleccione el sentido del traslado",
                )
            )
        for field in required:
            if getattr(request, field) is None:
                request.issues.append(
                    Issue(
                        code="required",
                        field=field,
                        message="Campo requerido para conciliar la solicitud",
                    )
                )
        if request.terminal_id is None:
            request.issues.append(
                Issue(
                    code="terminal_unresolved",
                    field="terminal_id",
                    message="El terminal requiere vinculación explícita",
                )
            )
        if request.phone:
            try:
                normalize_phone(request.phone)
            except ValueError:
                request.issues.append(
                    Issue(
                        code="phone_invalid",
                        field="phone",
                        message="Revise el teléfono, sin completar dígitos",
                    )
                )
        if request.address and (
            len(request.address) < 8
            or not re.search(
                r"\d|s/n",
                request.address.lower(),
            )
        ):
            request.issues.append(
                Issue(
                    code="address_incomplete",
                    field="address",
                    message="Revise calle y numeración explícitas",
                )
            )
        if (
            expected_service_date
            and request.service_date
            and (request.service_date != expected_service_date)
        ):
            request.issues.append(
                Issue(
                    code="date_context_conflict",
                    field="service_date",
                    message="La fecha difiere del contexto indicado",
                )
            )
        if request.service_date:
            date_groups[request.direction].add(request.service_date)
        code = employee_identity(request.employee_code)
        if code:
            identity = ("code", code)
        elif request.name and request.phone:
            identity = ("name_phone", normalize(request.name), request.phone)
        elif request.name and request.address:
            identity = ("name_address", normalize(request.name), normalize(request.address))
        else:
            identity = ("unlinked", request.id)
        duplicate_groups[
            (request.customer_id, request.direction, request.service_date, identity)
        ].append(request)
    for group in duplicate_groups.values():
        if len(group) > 1:
            for request in group:
                request.issues.append(
                    Issue(
                        code="duplicate_candidate",
                        message="Posible duplicado conservado para revisión",
                        severity="warning",
                    )
                )
    for request in requests:
        if request.excluded:
            continue
        if len(date_groups[request.direction]) > 1:
            request.issues.append(
                Issue(
                    code="mixed_dates",
                    field="service_date",
                    message="Existen fechas diferentes en el mismo sentido",
                    severity="warning",
                )
            )
        request.validation_status = (
            ValidationStatus.REVIEW if request.issues else ValidationStatus.VALID
        )
    return requests


def parse_real_excel(
    content: bytes,
    customer_id: CustomerCode,
    role: DocumentRole,
    *,
    archive_date: date | None = None,
    expected_service_date: date | None = None,
    terminal: Terminal | None = None,
) -> IngestionResult:
    """Parse previews, retaining uncertain caches. No formula is evaluated or trusted by default."""
    customer_id, role = CustomerCode(customer_id), DocumentRole(role)
    if terminal and terminal.customer_id != customer_id:
        raise IngestionError("El terminal pertenece a otro cliente")
    if len(content) > 10 * 1024 * 1024:
        raise IngestionError("Máximo 10 MB por archivo")
    workbook = cached = None
    try:
        _check_archive(content)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            workbook = load_workbook(
                BytesIO(content), read_only=True, data_only=False, keep_links=False
            )
            cached = load_workbook(
                BytesIO(content), read_only=True, data_only=True, keep_links=False
            )
        return _parse_books(
            content,
            workbook,
            cached,
            customer_id,
            role,
            archive_date,
            expected_service_date,
            terminal,
        )
    except IngestionError:
        raise
    except Exception:
        # Never propagate exception text: it may contain a value, formula or private path.
        raise IngestionError("No se pudo interpretar el libro XLSX de forma segura") from None
    finally:
        if workbook:
            workbook.close()
        if cached:
            cached.close()


def _check_archive(content):
    with ZipFile(BytesIO(content)) as archive:
        if (
            len(archive.infolist()) > 2000
            or sum(entry.file_size for entry in archive.infolist()) > 50 * 1024 * 1024
        ):
            raise IngestionError("XLSX excede los límites descomprimidos")


def detect_original_customer(content: bytes, filename: str) -> CustomerCode:
    """Look for roster structure before considering a client label in the filename."""
    hints = set()
    recognition = False
    book = None
    try:
        _check_archive(content)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = load_workbook(BytesIO(content), read_only=True, keep_links=False)
        if len(book.worksheets) > 20:
            raise IngestionError("Máximo 20 hojas por archivo")
        profile = get_profile(CustomerCode.LO_BLANCO)
        generic_profile = get_profile(CustomerCode.GRAN_AMERICA)
        for sheet in book.worksheets:
            if sheet.sheet_state != "visible":
                continue
            title = normalize(sheet.title)
            if title.startswith(("base", "bd", "bbdd", "plantilla", "ruta", "reparto", "cierre")):
                continue
            for row in sheet.iter_rows(
                max_row=min(sheet.max_row or 100, 100), max_col=100, values_only=True
            ):
                fields = set(profile.header(row).values())
                if not {"service_date", "work_time", "address"} <= fields or fields & {
                    "arrival_time",
                    "pickup_time",
                }:
                    continue
                recognition = True
                labels = {normalize(value) for value in row if isinstance(value, str)}
                if labels & {"fecha presentacion", "fecha de presentacion", "deposito asignado"}:
                    hints.add(CustomerCode.LO_BLANCO)
                elif any(
                    profile.field(value) and not generic_profile.field(value) for value in row
                ):
                    hints.add(CustomerCode.LO_BLANCO)
                elif "acercamiento" in title and labels & {"hora inicio", "hora de inicio"}:
                    hints.add(CustomerCode.GRAN_AMERICA)
    except IngestionError:
        raise
    except Exception:
        raise IngestionError("No se pudo interpretar el libro XLSX de forma segura") from None
    finally:
        if book is not None:
            book.close()
    if recognition and not hints:
        name = re.sub(r"[^a-z0-9]+", " ", normalize(filename))
        for label, code in (
            ("gran america", CustomerCode.GRAN_AMERICA),
            ("lo blanco", CustomerCode.LO_BLANCO),
        ):
            if re.search(rf"\b{label}\b", name):
                hints.add(code)
    if len(hints) != 1:
        raise IngestionError(
            "No se pudo identificar un cliente único. Elígelo en Importación manual."
        )
    return hints.pop()


def _parse_books(
    content, workbook, cached, customer_id, role, archive_date, expected_service_date, terminal
):
    if len(workbook.worksheets) > 20:
        raise IngestionError("Máximo 20 hojas por archivo")
    profile = get_profile(customer_id)
    batch_id, digest = str(uuid4()), hashlib.sha256(content).hexdigest()
    requests, reports, unclassified = [], [], []
    total_cells = 0
    for sheet_index, ws in enumerate(workbook, start=1):
        if not ws.max_row or not ws.max_column or ws.max_row > 10001 or ws.max_column > 100:
            raise IngestionError("Dimensiones de hoja no admitidas")
        total_cells += ws.max_row * ws.max_column
        if total_cells > 2_000_000:
            raise IngestionError("Límite total de celdas excedido")
        raw_rows = list(ws.values)
        stored_rows = list(cached.worksheets[sheet_index - 1].values)
        headers = [
            (i, mapping) for i, row in enumerate(raw_rows) if (mapping := profile.header(row))
        ]
        category = profile.category(ws.title, raw_rows, headers, role)
        report = SheetReport(
            sheet_index=sheet_index, category=category, header_rows=[i + 1 for i, _ in headers]
        )
        reports.append(report)
        if category != "active_roster":
            report.review_required = category in {
                "reference_or_unrecognized",
                "route_or_unclassified_reference",
            } and (
                ws.sheet_state == "visible"
                and any(any(v is not None for v in row) for row in raw_rows)
            )
            if report.review_required:
                unclassified.extend(
                    _quarantine_rows(
                        raw_rows,
                        stored_rows,
                        profile,
                        batch_id,
                        customer_id,
                        digest,
                        sheet_index,
                    )
                )
                if len(requests) + len(unclassified) > 10000:
                    raise IngestionError("Máximo 10000 filas de ingesta por archivo")
            continue
        mapping, header_row, block = {}, 0, 0
        header_map, ignored = dict(headers), Counter()
        for row_index, raw in enumerate(raw_rows):
            if row_index in header_map:
                mapping, header_row = header_map[row_index], row_index + 1
                block += 1
                continue
            if not mapping:
                continue
            stored = stored_rows[row_index] if row_index < len(stored_rows) else ()
            values = {
                field: (stored[col] if col < len(stored) else None)
                for col, field in mapping.items()
            }
            # A code or a person-bearing field is needed; ordinal-only/template rows are not people.
            identity_signal = any(meaningful(values.get(f)) for f in ("employee_code", "name"))
            other_signal = any(meaningful(values.get(f)) for f in ("address", "commune", "phone"))
            sentinel = [normalize(values.get(f)) for f in ("name", "address", "commune")]
            if not meaningful(values.get("employee_code")) and len(set(sentinel)) == 1:
                identity_signal = False
                other_signal = False
            if not identity_signal and not other_signal:
                explicit_schedule = any(
                    field in {"work_time", "end_time"}
                    and col < len(raw)
                    and meaningful(raw[col])
                    and not (isinstance(raw[col], str) and raw[col].startswith("="))
                    and _is_clock(raw[col])
                    for col, field in mapping.items()
                )
                if explicit_schedule:
                    unclassified.append(
                        _review_row(
                            raw,
                            stored,
                            mapping,
                            batch_id,
                            customer_id,
                            digest,
                            sheet_index,
                            row_index + 1,
                            header_row,
                            block,
                        )
                    )
                    report.review_required = True
                    ignored["scheduled_row_quarantined"] += 1
                    continue
                ignored["empty_template_or_annotation"] += 1
                continue
            request = _request(
                mapping,
                raw,
                stored,
                batch_id,
                customer_id,
                digest,
                sheet_index,
                row_index + 1,
                header_row,
                block,
                terminal,
            )
            for col, field in mapping.items():
                if profile.uses_header_variant(raw_rows[header_row - 1][col]):
                    request.issues.append(
                        Issue(
                            code="source_header_variant",
                            field=field,
                            severity="warning",
                            message="Encabezado anotado: confirme la interpretación del campo",
                        )
                    )
            requests.append(request)
            report.records += 1
            if len(requests) > 10000:
                raise IngestionError("Máximo 10000 solicitudes por archivo")
        report.ignored_rows = dict(ignored)
    validate_requests(requests, expected_service_date)
    if len(requests) + len(unclassified) > 10000:
        raise IngestionError("Máximo 10000 filas de ingesta por archivo")
    pending = sum(r.validation_status == ValidationStatus.REVIEW for r in requests)
    return IngestionResult(
        batch=IngestionBatch(
            id=batch_id,
            customer_id=customer_id,
            role=role,
            archive_date=archive_date,
            expected_service_date=expected_service_date,
            terminal_context_id=terminal.id if terminal else None,
            document_sha256=digest,
            created_at=datetime.now(UTC),
            records=len(requests),
            pending_review=pending,
            excluded=0,
            unclassified_rows=len(unclassified),
            status="pending_review"
            if pending or any(s.review_required for s in reports) or not requests
            else "interpreted",
            sheets=reports,
        ),
        requests=requests,
        unclassified_rows=unclassified,
    )


def _quarantine_rows(raw_rows, stored_rows, profile, batch_id, customer_id, digest, sheet_index):
    """Preserve uncertain visible rows without claiming that they are active ride requests."""
    candidates = [
        (i, {col: profile.field(v) for col, v in enumerate(row) if profile.field(v)})
        for i, row in enumerate(raw_rows[:30])
    ]
    header_index, mapping = max(candidates, key=lambda item: len(item[1]), default=(0, {}))
    start = header_index + 1 if mapping else 0
    result = []
    for index, raw in enumerate(raw_rows[start:], start=start):
        if not any(v is not None for v in raw):
            continue
        stored = stored_rows[index] if index < len(stored_rows) else ()
        result.append(
            _review_row(
                raw,
                stored,
                mapping,
                batch_id,
                customer_id,
                digest,
                sheet_index,
                index + 1,
                header_index + 1 if mapping else 0,
                0,
            )
        )
    return result


def _is_clock(value):
    try:
        parse_time(value)
        return True
    except (ValueError, TypeError):
        return False


def _review_row(
    raw, stored, mapping, batch_id, customer_id, digest, sheet_index, row, header_row, block
):
    cells = []
    for col, value in enumerate(raw):
        if value is None:
            continue
        cached = stored[col] if col < len(stored) else None
        formula = value if isinstance(value, str) and value.startswith("=") else None
        cells.append(
            CellEvidence(
                field=mapping.get(col),
                column=get_column_letter(col + 1),
                raw_value=json_value(value),
                formula=formula,
                stored_value=json_value(cached),
                origin="cached_unverified"
                if formula and cached is not None
                else "unresolved"
                if formula
                else "literal",
            )
        )
    return UnclassifiedRow(
        id=str(uuid4()),
        batch_id=batch_id,
        customer_id=customer_id,
        provenance=Provenance(
            document_sha256=digest,
            sheet_index=sheet_index,
            row=row,
            header_row=header_row,
            block=block,
        ),
        cells=cells,
    )


def _request(
    mapping,
    raw,
    stored,
    batch_id,
    customer_id,
    digest,
    sheet_index,
    row,
    header_row,
    block,
    terminal,
):
    evidence, issues, data = [], [], {}
    counts = Counter(mapping.values())
    for col, field in mapping.items():
        raw_value = raw[col] if col < len(raw) else None
        cache = stored[col] if col < len(stored) else None
        formula = raw_value if isinstance(raw_value, str) and raw_value.startswith("=") else None
        evidence.append(
            CellEvidence(
                field=field,
                column=get_column_letter(col + 1),
                raw_value=json_value(raw_value),
                formula=formula,
                stored_value=json_value(cache),
                origin="cached_unverified"
                if formula and cache is not None
                else "unresolved"
                if formula
                else "literal",
            )
        )
        if counts[field] > 1:
            data[field] = None
            issues.append(
                Issue(
                    code="source_ambiguous_columns",
                    field=field,
                    message="Varias columnas posibles; seleccione el dato explícitamente",
                )
            )
            continue
        selected = cache if formula else raw_value
        if formula:
            issues.append(
                Issue(
                    code="source_cached_unverified",
                    field=field,
                    severity="warning",
                    message="Fórmula conservada; caché no verificada",
                )
            )
            if re.search(r"\b(?:TODAY|NOW)\s*\(", formula, re.IGNORECASE):
                issues.append(
                    Issue(
                        code="source_volatile_formula",
                        field=field,
                        message="Fórmula temporal: requiere fecha histórica verificada",
                    )
                )
            if "[" in formula and "]" in formula:
                issues.append(
                    Issue(
                        code="source_external_reference",
                        field=field,
                        message="Referencia externa no resuelta ni consultada",
                    )
                )
            if cache is None:
                issues.append(
                    Issue(
                        code="source_formula_without_cache",
                        field=field,
                        message="La fórmula no tiene resultado almacenado",
                    )
                )
        try:
            data[field] = convert(field, selected)
            if field in TIME_FIELDS and isinstance(selected, datetime) and selected.year >= 2000:
                issues.append(
                    Issue(
                        code="source_clock_date_component",
                        field=field,
                        message="La hora incluye una fecha que requiere revisión",
                    )
                )
        except (ValueError, TypeError, ValidationError):
            data[field] = None
            issues.append(
                Issue(
                    code="source_invalid_value",
                    field=field,
                    message="Valor no interpretable; original conservado",
                )
            )
    has_start = "work_time" in mapping.values()
    has_end = "end_time" in mapping.values()
    data["direction"] = (
        Direction.INBOUND
        if has_start and not has_end
        else (Direction.OUTBOUND if has_end and not has_start else Direction.UNKNOWN)
    )
    terminal_name = data.get("terminal_name")
    if terminal and (not terminal_name or normalize(terminal_name) == normalize(terminal.name)):
        data["terminal_id"] = terminal.id
    elif terminal:
        issues.append(
            Issue(
                code="source_terminal_conflict",
                field="terminal_id",
                message="El terminal escrito difiere del terminal de contexto",
            )
        )
    # Validate each field earlier so a malformed cell never discards the rest of a request.
    return TransportRequest(
        **RequestData(**data).model_dump(),
        id=str(uuid4()),
        batch_id=batch_id,
        customer_id=customer_id,
        issues=issues,
        evidence=evidence,
        provenance=Provenance(
            document_sha256=digest,
            sheet_index=sheet_index,
            row=row,
            header_row=header_row,
            block=block,
            terminal_origin="source_match"
            if terminal and data.get("terminal_id") and terminal_name
            else "context"
            if data.get("terminal_id")
            else "none",
        ),
    )
