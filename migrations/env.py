import os
import sys
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Make the ``server`` package root importable regardless of the shell CWD.
SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

load_dotenv(SERVER_DIR / ".env")

from db.base import Base  # noqa: E402
import models.daily_fault_model  # noqa: E402,F401
import models.garage_service_model  # noqa: E402,F401
import models.machines_model  # noqa: E402,F401
import models.machine_photo_model  # noqa: E402,F401
import models.maintenance_model  # noqa: E402,F401
import models.repair_model  # noqa: E402,F401
import models.user_model  # noqa: E402,F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _alembic_database_url() -> str:
    """Read the DB URL from the environment; never commit credentials."""
    url = os.getenv("ALEMBIC_DATABASE_URL") or os.getenv("DATABASE_URL")
    if url:
        if url.startswith("postgres://"):
            return "postgresql+psycopg2://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            return "postgresql+psycopg2://" + url[len("postgresql://"):]
        if url.startswith("postgresql+asyncpg://"):
            return "postgresql+psycopg2://" + url[len("postgresql+asyncpg://"):]
        return url

    required = ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing database configuration for Alembic: " + ", ".join(missing)
        )

    return (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:"
        f"{quote_plus(os.getenv('DB_PASSWORD'))}@"
        f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/"
        f"{os.getenv('DB_NAME')}"
    )


# Alembic's ConfigParser treats '%' as interpolation; escape it.
config.set_main_option(
    "sqlalchemy.url", _alembic_database_url().replace("%", "%%")
)

# Model metadata is required for ``alembic revision --autogenerate``.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
