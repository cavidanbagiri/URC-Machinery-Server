


import os
from pathlib import Path

from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load server/.env before importing routers: database.setup reads env at import.
load_dotenv(Path(__file__).resolve().parent / ".env")

from routers import auth_router, machines_router, maintenance_router  # noqa: E402

app = FastAPI()


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


@app.get("/api/health", tags=["Health"])
async def health():
    return {"status": "ok"}




