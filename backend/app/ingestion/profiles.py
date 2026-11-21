"""Header vocabulary based on structural audit, never on personal values or holdout rows."""

from dataclasses import dataclass

from app.ingestion.excel import normalize
from app.models.ingestion import CustomerCode, DocumentRole

COMMON = {
    "employee_code": {"codigo", "codigo trabajador", "codigo de trabajador", "codigo conductor"},
    "name": {
        "nombre",
        "nombres",
        "nombre completo",
        "nombre y apellidos",
        "nombres y apellidos",
        "nombres apellidos",
        "nombre apellidos",
        "pasajero",
        "conductor",
        "condu",
    },
    "address": {"direccion", "domicilio", "direccion completa", "direccion recogida"},
    "commune": {"comuna", "sector"},
    "phone": {
        "telefono",
        "telefonos",
        "telef",
        "fono",
        "celular",
        "telefono de contacto",
        "telefono contacto",
        "numero telefono",
        "numero de telefono",
    },
    "service_date": {"fecha", "fecha servicio", "fecha de servicio", "fecha del servicio"},
    "work_time": {
        "hora inicio",
        "hora de inicio",
        "hora ingreso",
        "hora de ingreso",
        "hora entrada",
        "hora de entrada",
        "ingreso",
    },
    "end_time": {"hora termino", "hora de termino", "hora fin", "hora de fin"},
    "pickup_time": {
        "hora recogida",
        "hora de recogida",
        "hora retiro",
        "hora de retiro",
        "hora de recogida estimada",
        "hora recogida estimada",
    },
    "arrival_time": {
        "hora llegada deposito",
        "hora de llegada deposito",
        "hora llegada al deposito",
        "hora de llegada al deposito",
    },
    "terminal_name": {"terminal", "deposito", "destino"},
}


@dataclass(frozen=True)
class IngestionProfile:
    customer_id: CustomerCode
    aliases: dict[str, set[str]]

    def field(self, value) -> str | None:
        if not isinstance(value, str):
            return None
        label = normalize(value)
        for field, aliases in self.aliases.items():
            if label in aliases:
                return field
        # Some Lo Blanco headers append an annotation to this explicit prefix.
        # It is a preview mapping only: every affected row is marked for human review.
        if self.customer_id == CustomerCode.LO_BLANCO and label.startswith("hora de ingreso "):
            return "work_time"
        return None

    def uses_header_variant(self, value) -> bool:
        field = self.field(value)
        return field is not None and normalize(value) not in self.aliases[field]

    def header(self, row) -> dict[int, str]:
        mapping = {i: self.field(v) for i, v in enumerate(row) if self.field(v)}
        fields = set(mapping.values())
        identity = bool(fields & {"employee_code", "name"})
        clock = bool(fields & {"work_time", "end_time"})
        details = bool(fields & {"address", "commune", "phone"})
        return mapping if identity and clock and details else {}

    def category(self, title, rows, headers, role: DocumentRole) -> str:
        title = normalize(title)
        if not headers:
            labels = " ".join(normalize(v) for row in rows[:1] for v in row if isinstance(v, str))
            if ("contrato" in labels and "fecha" in labels) or (
                title.startswith(("base", "bd", "bbdd"))
            ):
                return "reference_master"
            return "reference_or_unrecognized"
        fields = set().union(*(set(m.values()) for _, m in headers))
        # Labour/reference tables must never turn into active ride requests.
        first_labels = " ".join(normalize(v) for row in rows[:1] for v in row if isinstance(v, str))
        if "contrato" in first_labels and "fecha" in first_labels:
            return "reference_master"
        if "arrival_time" in fields or "observacion" in title:
            return "closure_reference"
        if role == DocumentRole.INTERNAL:
            if "ruta" in title.split() or any(w.startswith("ruta") for w in title.split()):
                return "route_reference"
            if self.customer_id == CustomerCode.LO_BLANCO:
                if "acercamiento" not in title:
                    if "pickup_time" in fields and any(
                        normalize(v) == "terminal" for i, _ in headers for v in rows[i]
                    ):
                        return "route_reference"
                    return "route_or_unclassified_reference"
            elif "pickup_time" in fields and "acercamiento" not in title:
                return "route_or_unclassified_reference"
        return "active_roster"


def get_profile(customer_id: CustomerCode) -> IngestionProfile:
    aliases = {key: set(values) for key, values in COMMON.items()}
    if customer_id == CustomerCode.LO_BLANCO:
        aliases["service_date"].update({"fecha presentacion", "fecha de presentacion"})
        aliases["terminal_name"].add("deposito asignado")
        aliases["work_time"].update({"hora de ingreso al trabajo", "hora ingreso al trabajo"})
        aliases["name"].add("nombre y apellido")
    return IngestionProfile(customer_id, aliases)
