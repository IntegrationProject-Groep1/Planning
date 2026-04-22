"""Shared database configuration helpers."""

import os
from typing import Optional


def _first_env(*names: str, default: Optional[str] = None) -> Optional[str]:
    """Return the first non-empty environment variable from names."""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def get_db_config(default_host: str = "planning_db", default_port: str = "5432") -> dict[str, str]:
    """Return normalized DB connection settings.

    Supports both the legacy POSTGRES_* variables and the deployment DB_* variables.
    """
    return {
        "host": _first_env("DB_HOST_PLANNING", "DB_HOST", "POSTGRES_HOST", default=default_host) or default_host,
        "port": _first_env("DB_PORT_PLANNING", "DB_PORT", "POSTGRES_PORT", default=default_port) or default_port,
        "name": _first_env("DB_NAME_PLANNING", "DB_NAME", "POSTGRES_DB", default="planning_db") or "planning_db",
        "user": _first_env("DB_USER_PLANNING", "DB_USER", "POSTGRES_USER", default="planning_user") or "planning_user",
        "password": _first_env("DB_PASS_PLANNING", "DB_PASS", "POSTGRES_PASSWORD", default="") or "",
    }


def get_database_url(default_host: str = "planning_db", default_port: str = "5432") -> str:
    """Return DATABASE_URL or build one from the supported env vars."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    config = get_db_config(default_host=default_host, default_port=default_port)
    return "postgresql://{user}:{password}@{host}:{port}/{db}".format(
        user=config["user"],
        password=config["password"],
        host=config["host"],
        port=config["port"],
        db=config["name"],
    )
