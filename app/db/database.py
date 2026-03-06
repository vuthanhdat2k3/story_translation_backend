from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import get_settings

settings = get_settings()

# Supabase and other hosted Postgres require SSL.
# Append ?sslmode=require to the URL if not already present and not local.
_db_url = settings.DATABASE_URL
if "localhost" not in _db_url and "127.0.0.1" not in _db_url and "sslmode" not in _db_url:
    _db_url += "?sslmode=require"

engine = create_engine(
    _db_url,
    pool_pre_ping=True,
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
