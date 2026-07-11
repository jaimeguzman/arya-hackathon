"""Guarantee 1: fake data only.

Every DB write must carry is_synthetic=True, and the app refuses to boot
unless DATABASE_URL points at an allowlisted demo database name.
"""

from urllib.parse import urlparse

ALLOWED_DEMO_DB_NAMES = frozenset({"intakeai_demo", "intakeai_test"})


class SyntheticDataViolation(RuntimeError):
    """Raised when a record without is_synthetic=True reaches the write layer."""


class DisallowedDatabaseError(RuntimeError):
    """Raised at boot when DATABASE_URL is not an allowlisted demo database."""


def assert_synthetic(record: dict) -> dict:
    """Hard assertion applied to every DB write. Returns the record unchanged."""
    if record.get("is_synthetic") is not True:
        raise SyntheticDataViolation(
            "Refusing DB write: record is missing is_synthetic=True. "
            "Only synthetic data may enter this system."
        )
    return record


def validate_database_url(database_url: str) -> str:
    """Boot-time check: the database name must be in the demo allowlist."""
    db_name = urlparse(database_url).path.lstrip("/")
    if db_name not in ALLOWED_DEMO_DB_NAMES:
        raise DisallowedDatabaseError(
            f"Refusing to boot: database '{db_name}' is not an allowlisted demo "
            f"database ({sorted(ALLOWED_DEMO_DB_NAMES)})."
        )
    return database_url
