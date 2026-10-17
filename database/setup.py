

# production
import os
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _build_connection_string() -> str:
    """Build the async DB URL from env vars.

    Render exposes ``DATABASE_URL``; local development uses the five ``DB_*``
    variables. Credentials are URL-encoded so special characters are safe.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        if database_url.startswith("postgres://"):
            return "postgresql+asyncpg://" + database_url[len("postgres://"):]
        if database_url.startswith("postgresql://"):
            return "postgresql+asyncpg://" + database_url[len("postgresql://"):]
        if database_url.startswith("postgresql+psycopg2://"):
            return "postgresql+asyncpg://" + database_url[len("postgresql+psycopg2://"):]
        return database_url

    required = ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing database configuration: " + ", ".join(missing)
        )

    return (
        f"postgresql+asyncpg://{os.getenv('DB_USER')}:"
        f"{quote_plus(os.getenv('DB_PASSWORD'))}@"
        f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/"
        f"{os.getenv('DB_NAME')}"
    )


connection_string = _build_connection_string()

engine = create_async_engine(
    connection_string,
    echo=False,  # Set to False for production/load testing
    pool_pre_ping=True,
    pool_size=20,       # Increased from 5
    max_overflow=30,    # Increased from 5
    pool_recycle=3600,  # Recycle connections every hour
    pool_timeout=30,    # Wait 30 seconds for connection
)



# Session factory
SessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()

