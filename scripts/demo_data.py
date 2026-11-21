"""Public landmarks and resource presets shared by both demonstration servers."""

import json
from pathlib import Path

from app.geo.models import Candidate
from app.geo.providers import GeoProviderError, SyntheticRoadProvider, rounded
from app.models.entities import DepotRow, DriverRow, TerminalRow, VehicleRow
from app.models.ingestion import CustomerCode, Terminal
from app.models.schemas import Depot, Driver, Vehicle
from app.optimization.travel import TravelMatrix

STOPS = (
    (
        "Centro Gabriela Mistral",
        "Av. Libertador Bernardo O'Higgins 227",
        "Santiago",
        -33.43964,
        -70.64053,
    ),
    (
        "Biblioteca Nacional",
        "Av. Libertador Bernardo O'Higgins 651",
        "Santiago",
        -33.44226,
        -70.64574,
    ),
    (
        "Museo Nacional de Bellas Artes",
        "José Miguel de la Barra 650",
        "Santiago",
        -33.43587,
        -70.64379,
    ),
    ("Museo de la Memoria", "Matucana 501", "Santiago", -33.43969, -70.68017),
    ("Biblioteca de Santiago", "Matucana 151", "Santiago", -33.44643, -70.68147),
    ("Teatro Municipal", "Agustinas 794", "Santiago", -33.44070, -70.64794),
    ("Museo de Arte Precolombino", "Bandera 361", "Santiago", -33.43831, -70.65247),
    ("Museo Histórico Nacional", "Plaza de Armas 951", "Santiago", -33.43702, -70.65080),
    ("Casa Central UC", "Alameda 340", "Santiago", -33.44127, -70.64229),
    ("Centro Cultural Matucana 100", "Av. Matucana 100", "Estación Central", -33.44758, -70.68135),
    ("Municipalidad de Pudahuel", "Av. San Pablo 8444", "Pudahuel", -33.44234, -70.75313),
    ("OMIL Maipú", "Alberto Llona 1889", "Maipú", -33.50905, -70.75648),
    ("Municipalidad de Lo Prado", "Av. San Pablo 5959", "Lo Prado", -33.44174, -70.72377),
    ("Municipalidad de Renca", "Blanco Encalada 1335", "Renca", -33.40325, -70.72002),
    (
        "Municipalidad de Independencia",
        "Av. Independencia 753",
        "Independencia",
        -33.42398,
        -70.65573,
    ),
    ("OMIL Quinta Normal", "Carrascal 4696", "Quinta Normal", -33.42706, -70.70058),
    ("Municipalidad de Cerro Navia", "Del Consistorial 6645", "Cerro Navia", -33.42238, -70.73646),
    (
        "Oficina municipal de Quilicura",
        "José Francisco Vergara 450",
        "Quilicura",
        -33.36598,
        -70.73141,
    ),
    ("Oficina pública de Cerrillos", "Las Hortensias 400", "Cerrillos", -33.49855, -70.71528),
    ("Café Literario Parque Balmaceda", "Av. Providencia 410", "Providencia", -33.43687, -70.62991),
    ("Biblioteca municipal de Ñuñoa", "Av. Irarrázaval 4055", "Ñuñoa", -33.45286, -70.58777),
    ("Museo Interactivo Mirador", "Av. Punta Arenas 6711", "La Granja", -33.51632, -70.61471),
)
TERMINALS = {
    CustomerCode.GRAN_AMERICA: (
        "Llegada simulada · Centro Cultural La Moneda",
        "Plaza de la Ciudadanía 26",
        -33.44310,
        -70.65357,
    ),
    CustomerCode.LO_BLANCO: (
        "Llegada simulada · Centro Cultural Matucana 100",
        "Av. Matucana 100",
        -33.44758,
        -70.68135,
    ),
}
demo_points = {
    address.casefold(): [
        Candidate(
            id=f"demo-{index}",
            latitude=latitude,
            longitude=longitude,
            context_match=True,
        )
    ]
    for index, (_, address, _, latitude, longitude) in enumerate(STOPS)
}


class DemoRoadSnapshot(SyntheticRoadProvider):
    """Road estimates for public sample points only, without runtime routing requests."""

    name = "OSRM / FOSSGIS · OpenStreetMap (demo)"
    cache_scope = "santiago_public_demo"

    def __init__(self, path: Path):
        fixture = json.loads(path.read_text())
        self.version = "osm-" + fixture["captured"]
        self.index = {tuple(point): i for i, point in enumerate(fixture["points"])}
        self.seconds = rounded(fixture["seconds"])
        self.meters = rounded(fixture["meters"])
        TravelMatrix(self.seconds, self.meters, self.name, True).validate(len(self.index))

    def matrix(self, locations, *, departure_at=None):
        try:
            indexes = [self.index[(point.latitude, point.longitude)] for point in locations]
        except KeyError:
            raise GeoProviderError(
                "Usa los orígenes y puntos públicos incluidos en la demo."
            ) from None
        return TravelMatrix(
            [[self.seconds[i][j] for j in indexes] for i in indexes],
            [[self.meters[i][j] for j in indexes] for i in indexes],
            self.name,
            True,
            self.version,
        )


snapshot = Path(__file__).resolve().parents[1] / "data/synthetic/santiago-road-demo.json"


def road_demo():
    return DemoRoadSnapshot(snapshot) if snapshot.is_file() else SyntheticRoadProvider()


def seed_resources(db):
    depot = Depot(
        id="base-demo",
        name="Base simulada · Biblioteca de Santiago",
        address=STOPS[4][1],
        latitude=STOPS[4][3],
        longitude=STOPS[4][4],
    )
    db.add(DepotRow(id=depot.id, payload=depot.model_dump(mode="json")))
    for customer in CustomerCode:
        name, address, latitude, longitude = TERMINALS[customer]
        terminal = Terminal(
            id=f"terminal-{customer}",
            customer_id=customer,
            name=name,
            address=address,
            latitude=latitude,
            longitude=longitude,
        )
        db.add(
            TerminalRow(
                id=terminal.id,
                customer_id=customer,
                payload=terminal.model_dump(mode="json"),
            )
        )
    for index in range(1, 4):
        vehicle = Vehicle(id=f"van-{index}", identifier=f"Van {index:02}")
        driver = Driver(
            id=f"team-{index}",
            identifier=f"Conductor {index:02}",
            vehicle_id=vehicle.id,
            max_trips=2,
        )
        db.add(
            VehicleRow(
                id=vehicle.id,
                identifier=vehicle.identifier,
                payload=vehicle.model_dump(mode="json"),
            )
        )
        db.flush()
        db.add(
            DriverRow(
                id=driver.id,
                identifier=driver.identifier,
                vehicle_id=vehicle.id,
                payload=driver.model_dump(mode="json"),
            )
        )
    db.commit()
