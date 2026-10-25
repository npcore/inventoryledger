import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(os.environ.get("INVENTORY_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATABASE_URL = os.environ.get("INVENTORY_DATABASE_URL", f"sqlite:///{DATA_DIR / 'inventory.db'}")


class Base(DeclarativeBase):
    pass


def make_engine(url: str = DATABASE_URL):
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(bind=None) -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(bind or engine)
