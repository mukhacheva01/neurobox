#!/bin/bash
set -e
echo "=== НейроБокс admin ==="
exec python -m services.admin.app
