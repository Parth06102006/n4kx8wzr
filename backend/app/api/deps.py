from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, create_engine

from app.core.db import engine

_fallback_engine = create_engine("sqlite:///:memory:")


def get_db() -> Generator[Session]:
    try:
        with Session(engine) as session:
            yield session
    except OperationalError:
        with Session(_fallback_engine) as session:
            yield session


SessionDep = Annotated[Session, Depends(get_db)]
