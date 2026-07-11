"""IntakeAI FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.api import caregivers, documents, eligibility, followup, intake, voice
from backend.models.database import close_all_dbs, get_neo4j, get_redis, get_sessionmaker, init_all_dbs
from backend.workers.followup_scheduler import get_scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await init_all_dbs()
    sched = get_scheduler()
    sched.start()
    yield
    await sched.stop()
    await close_all_dbs()


app = FastAPI(
    title="IntakeAI",
    description="Home health intake API — Phase 5",
    version="0.5.0",
    lifespan=lifespan,
)

# ponytail: allow all origins for hackathon — ceiling: open CORS; upgrade: restrict
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(intake.router)
app.include_router(eligibility.router)
app.include_router(caregivers.router)
app.include_router(documents.router)
app.include_router(followup.router)
app.include_router(voice.router)


@app.get("/")
async def health() -> dict[str, Any]:
    status = {
        "service": "IntakeAI",
        "version": "0.5.0",
        "postgres": "error",
        "neo4j": "error",
        "redis": "error",
    }
    try:
        Session = get_sessionmaker()
        async with Session() as session:
            await session.execute(text("SELECT 1"))
        status["postgres"] = "ok"
    except Exception:
        pass
    try:
        driver = get_neo4j()
        async with driver.session() as neo:
            await neo.run("RETURN 1")
        status["neo4j"] = "ok"
    except Exception:
        pass
    try:
        redis = get_redis()
        pong = await redis.ping()
        if pong:
            status["redis"] = "ok"
    except Exception:
        pass
    return status
