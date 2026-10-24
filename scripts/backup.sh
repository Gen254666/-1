#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
DATABASE_URL="${DATABASE_URL_AGENT:-}"
CHROMA_PATH="${CHROMA_PATH:-./data/chroma}"

if [[ -z "${DATABASE_URL}" ]]; then
  echo "DATABASE_URL_AGENT is required (use postgresql:// not postgresql+asyncpg://)" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
STAMP="$(date +%Y%m%d-%H%M%S)"

PG_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"
pg_dump "${PG_URL}" -Fc -f "${BACKUP_DIR}/steel_market-${STAMP}.dump"
echo "database backup: ${BACKUP_DIR}/steel_market-${STAMP}.dump"

if [[ -d "${CHROMA_PATH}" ]]; then
  tar -czf "${BACKUP_DIR}/chroma-${STAMP}.tar.gz" -C "$(dirname "${CHROMA_PATH}")" "$(basename "${CHROMA_PATH}")"
  echo "chroma backup: ${BACKUP_DIR}/chroma-${STAMP}.tar.gz"
fi
