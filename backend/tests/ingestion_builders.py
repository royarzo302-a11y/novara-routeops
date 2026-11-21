"""Entirely fictitious workbook structures. Never load or derive values from data/real."""

from datetime import date, datetime
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook
from openpyxl.utils.datetime import to_excel

DAY = date(2026, 11, 10)
GA = [
    "N°",
    "Fecha",
    "Hora Inicio",
    "Código",
    "Nombres y Apellidos",
    "Dirección",
    "Comuna",
    "Teléfono",
]
LB = [
    "Depósito asignado",
    "Fecha de presentación",
    "Hora de ingreso",
    "Área de trabajo",
    "Código",
    "Nombre y Apellidos",
    "Teléfono de contacto",
    "Dirección",
    "Nota",
    "Comuna",
]


def ga_row(code="SIM-001", name="Persona Sintética Uno", day=DAY):
    return [1, day, "05:00", code, name, "Calle Ficticia 101", "Comuna Sintética", "970000001"]


def lb_row(code="SIM-001"):
    return [
        "Terminal Sintético",
        DAY,
        "05:00",
        "Área Sintética",
        code,
        "Persona Sintética Uno",
        "970000001",
        "Calle Ficticia 101",
        None,
        "Comuna Sintética",
    ]


def workbook(sheets, caches=None, hidden=None):
    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets:
        ws = book.create_sheet(title)
        for row in rows:
            ws.append(row)
    for (index, address), value in (caches or {}).items():
        if isinstance(value, (date, datetime)):
            book.worksheets[index - 1][address].number_format = "yyyy-mm-dd"
    for index in hidden or []:
        book.worksheets[index - 1].sheet_state = "hidden"
    output = BytesIO()
    book.save(output)
    if not caches:
        return output.getvalue()
    # Excel caches are written into SYNTHETIC bytes only; formulas are never evaluated.
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    result = BytesIO()
    with (
        ZipFile(BytesIO(output.getvalue())) as source,
        ZipFile(result, "w", ZIP_DEFLATED) as target,
    ):
        for member in source.infolist():
            data = source.read(member.filename)
            if member.filename.startswith("xl/worksheets/sheet"):
                for (index, address), value in caches.items():
                    if member.filename != f"xl/worksheets/sheet{index}.xml":
                        continue
                    root = ET.fromstring(data)
                    cell = root.find(f".//{namespace}c[@r='{address}']")
                    assert cell is not None
                    stored = cell.find(f"{namespace}v")
                    if stored is None:
                        stored = ET.SubElement(cell, f"{namespace}v")
                    if isinstance(value, (date, datetime)):
                        cell.set("t", "n")
                        stored.text = str(to_excel(value))
                    elif isinstance(value, str):
                        cell.set("t", "str")
                        stored.text = value
                    else:
                        cell.set("t", "n")
                        stored.text = str(value)
                    data = ET.tostring(root)
            target.writestr(member, data)
    return result.getvalue()
