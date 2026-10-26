from sqlmodel import Session, create_engine, select

from app.core.config import settings

engine = create_engine(str(settings.DATABASE_URL), pool_pre_ping=True)


def init_db(session: Session) -> None:
    """Verify DB connectivity; tables are created via Alembic migrations."""
    session.exec(select(1))
