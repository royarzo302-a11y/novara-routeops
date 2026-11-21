from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, CustomerRow


def database(url: str):
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url.endswith(":memory:"):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def initialize(engine):
    Base.metadata.create_all(engine)
    # Additive tables only: existing v0.1 SQLite schemas and data remain compatible.
    with sessionmaker(bind=engine)() as db:
        for code, name in (("gran_america", "Gran América"), ("lo_blanco", "Lo Blanco")):
            if db.get(CustomerRow, code) is None:
                db.add(CustomerRow(id=code, name=name))
        db.commit()
