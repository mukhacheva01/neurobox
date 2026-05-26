#!/bin/bash
set -e
echo "=== НейроБокс backend ==="
echo "Running Alembic migrations..."
alembic upgrade head
echo "Starting uvicorn..."
exec uvicorn services.backend.main:app --host 0.0.0.0 --port "${ADMIN_API_PORT:-8092}"
