"""Database clients for PostgreSQL (SQLAlchemy), Neo4j, and Redis.

# ponytail: replaces spec get_pg() raw asyncpg pool — ceiling: ORM overhead;
# upgrade: keep Core for hot paths
"""

from __future__ import annotations

import logging
from typing import Optional

from neo4j import AsyncDriver, AsyncGraphDatabase
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import get_settings

logger = logging.getLogger(__name__)

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_neo4j_driver: Optional[AsyncDriver] = None
_redis_client: Optional[Redis] = None


async def init_postgres() -> None:
    """Initialize SQLAlchemy async engine and session factory."""
    global _engine, _session_factory
    settings = get_settings()
    _engine = create_async_engine(
        settings.sqlalchemy_database_uri,
        pool_size=2,
        max_overflow=8,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info("PostgreSQL engine initialized")


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory."""
    if _session_factory is None:
        raise RuntimeError("PostgreSQL not initialized — call init_postgres() first")
    return _session_factory


def get_session() -> AsyncSession:
    """Create a new AsyncSession (caller must close / use as context manager)."""
    return get_sessionmaker()()


async def close_postgres() -> None:
    """Dispose the SQLAlchemy engine."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("PostgreSQL engine closed")


async def init_neo4j() -> None:
    """Initialize Neo4j async driver."""
    global _neo4j_driver
    settings = get_settings()
    _neo4j_driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    logger.info("Neo4j driver initialized")


def get_neo4j() -> AsyncDriver:
    """Return the Neo4j async driver."""
    if _neo4j_driver is None:
        raise RuntimeError("Neo4j not initialized — call init_neo4j() first")
    return _neo4j_driver


async def close_neo4j() -> None:
    """Close the Neo4j driver."""
    global _neo4j_driver
    if _neo4j_driver is not None:
        await _neo4j_driver.close()
        _neo4j_driver = None
        logger.info("Neo4j driver closed")


async def init_redis() -> None:
    """Initialize Redis async client."""
    global _redis_client
    settings = get_settings()
    _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    logger.info("Redis client initialized")


def get_redis() -> Redis:
    """Return the Redis async client."""
    if _redis_client is None:
        raise RuntimeError("Redis not initialized — call init_redis() first")
    return _redis_client


async def close_redis() -> None:
    """Close the Redis client."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis client closed")


async def init_all_dbs() -> None:
    """Initialize Postgres, Neo4j, and Redis clients."""
    await init_postgres()
    await init_neo4j()
    await init_redis()


async def close_all_dbs() -> None:
    """Close all database clients."""
    await close_postgres()
    await close_neo4j()
    await close_redis()
