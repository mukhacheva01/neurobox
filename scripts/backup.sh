#!/bin/bash
# НейроБокс — PostgreSQL backup script.
#
# Install:
#   chmod +x /opt/neurobox/scripts/backup.sh
#   crontab -e → add:
#   0 3 * * * /opt/neurobox/scripts/backup.sh >> /var/log/neurobox_backup.log 2>&1
#
# Keeps 7 days of backups. Adjust RETENTION_DAYS as needed.

set -euo pipefail

BACKUP_DIR="/opt/neurobox/backups"
RETENTION_DAYS=7
DATE=$(date +%Y%m%d_%H%M%S)
FILENAME="neurobox_${DATE}.sql.gz"

# Postgres container: set NEUROBOX_POSTGRES_CONTAINER if your container has another name
POSTGRES_CONTAINER="${NEUROBOX_POSTGRES_CONTAINER:-neurobox-postgres-1}"
if ! docker exec "$POSTGRES_CONTAINER" pg_dump --version &>/dev/null; then
  POSTGRES_CONTAINER="neurobox_postgres_1"
fi

# Ensure backup dir exists
mkdir -p "${BACKUP_DIR}"

echo "[$(date)] Starting backup (container: ${POSTGRES_CONTAINER})..."

# Use docker exec to run pg_dump inside the postgres container
docker exec "$POSTGRES_CONTAINER" pg_dump \
    -U neurobox \
    --format=custom \
    --compress=6 \
    neurobox \
    > "${BACKUP_DIR}/${FILENAME}" 2>/dev/null

# Check if backup was created and has content
if [ -s "${BACKUP_DIR}/${FILENAME}" ]; then
    SIZE=$(du -h "${BACKUP_DIR}/${FILENAME}" | cut -f1)
    echo "[$(date)] Backup OK: ${FILENAME} (${SIZE})"
else
    echo "[$(date)] ERROR: Backup file is empty!"
    rm -f "${BACKUP_DIR}/${FILENAME}"
    exit 1
fi

# Cleanup old backups
DELETED=$(find "${BACKUP_DIR}" -name "neurobox_*.sql.gz" -mtime +${RETENTION_DAYS} -delete -print | wc -l)
echo "[$(date)] Cleaned up ${DELETED} old backups"

# Summary
TOTAL=$(ls -1 "${BACKUP_DIR}"/neurobox_*.sql.gz 2>/dev/null | wc -l)
echo "[$(date)] Total backups: ${TOTAL}"
