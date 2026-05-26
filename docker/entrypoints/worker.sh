#!/bin/bash
set -e
echo "=== НейроБокс worker ==="
exec python -m services.worker.main
