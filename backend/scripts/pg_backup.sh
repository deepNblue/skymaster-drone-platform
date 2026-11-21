#!/usr/bin/env bash
# SkyMaster PostgreSQL daily backup with 7-day rotation.
# Usage: scripts/pg_backup.sh  (expects psql tooling on PATH)
set -euo pipefail

BACKUP_DIR="${HOME}/skymaster_pg_backups"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${BACKUP_DIR}/skymaster_${STAMP}.dump"
KEEP=7
LOG="${BACKUP_DIR}/last_backup.log"

mkdir -p "${BACKUP_DIR}"

# pg_dump from the conda pg env (tools not on default PATH)
export PATH="${HOME}/miniconda3/envs/pg/bin:${PATH}"

{
  echo "== pg_backup ${STAMP} =="
  if pg_dump -h 127.0.0.1 -p 5433 -U postgres -Fc -f "${OUT}" skymaster; then
    SIZE=$(du -h "${OUT}" | cut -f1)
    echo "OK ${OUT} ${SIZE}"
    # rotate: keep newest ${KEEP}
    ls -1t "${BACKUP_DIR}"/skymaster_*.dump 2>/dev/null | tail -n +$((KEEP + 1)) \
      | while read -r old; do rm -f "${old}"; echo "rotated: ${old}"; done
    echo "kept: $(ls -1 "${BACKUP_DIR}"/skymaster_*.dump | wc -l) dumps"
  else
    echo "FAILED pg_dump exit=$?"
    exit 1
  fi
} >> "${LOG}" 2>&1
