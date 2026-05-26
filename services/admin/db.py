"""DB connection for admin panel (sync psycopg2)."""
import os

import psycopg2
from psycopg2.extras import RealDictCursor


def _get_database_url():
    url = os.environ.get("DATABASE_URL", "postgresql://neurobox:password@postgres:5432/neurobox")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url

def get_conn():
    return psycopg2.connect(_get_database_url(), cursor_factory=RealDictCursor)
