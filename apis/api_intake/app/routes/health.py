import socket
from urllib.parse import urlparse

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()

_CHECK_TIMEOUT_SECONDS = 0.5
_DEPENDENCY_DEFAULT_PORTS = {
    "postgres": 5432,
    "neo4j": 7687,
    "redis": 6379,
}


def _tcp_status(url: str, default_port: int) -> str:
    if not url:
        return "not_configured"
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or default_port
    if not host:
        return "not_configured"
    try:
        with socket.create_connection((host, port), timeout=_CHECK_TIMEOUT_SECONDS):
            return "ok"
    except OSError:
        return "unavailable"


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    dependencies = {
        "postgres": _tcp_status(settings.database_url, _DEPENDENCY_DEFAULT_PORTS["postgres"]),
        "neo4j": _tcp_status(settings.neo4j_uri, _DEPENDENCY_DEFAULT_PORTS["neo4j"]),
        "redis": _tcp_status(settings.redis_url, _DEPENDENCY_DEFAULT_PORTS["redis"]),
    }
    degraded = any(status != "ok" for status in dependencies.values())
    return {"status": "degraded" if degraded else "ok", "dependencies": dependencies}
