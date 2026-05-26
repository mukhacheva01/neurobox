#!/bin/bash
# НейроБокс — ежедневный бэкап PostgreSQL
BACKUP_DIR=/opt/neurobox/backups
CONTAINER=neurobox_postgres
DB_NAME=neurobox
DB_USER=neurobox
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/neurobox_${DATE}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# Создать бэкап
docker exec ${CONTAINER} pg_dump -U ${DB_USER} ${DB_NAME} | gzip > "${BACKUP_FILE}"

# Проверка
SIZE=$(stat -c%s "${BACKUP_FILE}" 2>/dev/null || echo 0)
if [ "$SIZE" -lt 100 ]; then
    echo "ERROR: Backup file is too small (${SIZE} bytes): ${BACKUP_FILE}"
    rm -f "${BACKUP_FILE}"
    exit 1
fi

# Удалить бэкапы старше 14 дней
find ${BACKUP_DIR} -name "*.sql.gz" -mtime +14 -delete
find ${BACKUP_DIR} -name "*.dump" -mtime +14 -delete

echo "Backup OK: ${BACKUP_FILE} (${SIZE} bytes)"

# Rotate: delete backups older than 14 days
find /opt/neurobox/backups/ -name "neurobox_*.sql.gz" -mtime +14 -delete
