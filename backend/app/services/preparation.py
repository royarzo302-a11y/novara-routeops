from sqlalchemy import select

from app.models.entities import DepotRow, OperationSettingsRow, TerminalRow
from app.models.preparation import Preparation


def load_preparation(db, *, demo=False):
    if demo:
        depots = list(db.scalars(select(DepotRow)))
        terminals = list(db.scalars(select(TerminalRow)))
        return Preparation(
            depot_id=depots[0].id if len(depots) == 1 else None,
            terminal_ids={row.customer_id: row.id for row in terminals},
        )
    row = db.get(OperationSettingsRow, "preparation")
    return Preparation.model_validate(row.payload) if row else Preparation()
