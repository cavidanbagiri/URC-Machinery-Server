


import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load server/.env before importing routers: database.setup reads env at import.
load_dotenv(Path(__file__).resolve().parent / ".env")

from routers import auth_router, machines_router, maintenance_router, repair_router  # noqa: E402
from services.storage_service import missing_configuration  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Surface missing photo-storage configuration in the host's logs.

    Deployed services (Render, ...) do not read ``server/.env``; the variables
    must be created in the service environment. Without them uploads return 503
    and photo URLs are empty, so log the exact names once at startup.
    """

    missing = missing_configuration()
    if missing:
        logger.warning(
            "Machine photo storage is disabled, missing environment variables: %s",
            ", ".join(missing),
        )
    else:
        logger.info("Machine photo storage is configured")
    yield


app = FastAPI(lifespan=lifespan)


default_origins = [
    "http://localhost:5173",
    "https://urc-machinery-web.onrender.com"
]
configured_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
origins = configured_origins or default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


app.include_router(router = auth_router.router, prefix="/api/auth", tags=["User"])
app.include_router(router = machines_router.router, prefix="/api/machines", tags=["Machines"])
app.include_router(router = maintenance_router.router, prefix="/api/maintenance", tags=["Maintenance"])
app.include_router(router = repair_router.router, prefix="/api/repair", tags=["Repair"])


@app.get("/api/health", tags=["Health"])
async def health():
    missing = missing_configuration()
    return {
        "status": "ok",
        # Hosts without the S3_* environment variables can still serve the API,
        # but photo upload returns 503 and photo URLs are empty.
        "photo_storage": "disabled" if missing else "configured",
        "missing_settings": missing,
    }




