"""FastAPI application — USDA Grain Pipeline API.

Combines data collection control, grain data serving, image serving,
and scheduling in a single process.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from api.routers import collector, grain, images, schedule
from api.scheduler import get_scheduler, setup_default_jobs
from common.storage import ensure_dirs

log = logging.getLogger(__name__)

# USER-CONFIG: allowed CORS origins
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3020",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    scheduler = get_scheduler()
    setup_default_jobs(scheduler)
    scheduler.start()
    log.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))
    yield
    scheduler.shutdown(wait=False)
    log.info("Scheduler stopped")


app = FastAPI(
    title="USDA Grain Pipeline API",
    version="0.1.0",
    description="Data collection, grain data serving, image management, and scheduling",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(collector.router)
app.include_router(grain.router)
app.include_router(images.router)
app.include_router(schedule.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "usda-grain-pipeline"}


if __name__ == "__main__":
    import uvicorn
    # USER-CONFIG: API server host and port
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
