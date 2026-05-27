"""Sync psycopg2 connection helper for the admin panel."""
import psycopg2
from psycopg2.extras import RealDictCursor

from shared.config.runtime_urls import database_url_from_env


def _get_database_url():
    return database_url_from_env(async_driver=False)


def get_conn():
    return psycopg2.connect(_get_database_url(), cursor_factory=RealDictCursor)
