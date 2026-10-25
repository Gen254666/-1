#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export MSYS_NO_PATHCONV=1

BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
BACKUP_PASSPHRASE="${BACKUP_PASSPHRASE:-}"

if [[ -z "${BACKUP_PASSPHRASE}" ]]; then
  echo "BACKUP_PASSPHRASE is required" >&2
  exit 1
fi
if (( ${#BACKUP_PASSPHRASE} < 32 )) || [[ "${BACKUP_PASSPHRASE}" == CHANGE_ME* ]]; then
  echo "BACKUP_PASSPHRASE must be at least 32 characters and not a placeholder" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi
if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

STAMP="$(date +%Y%m%d-%H%M%S)"
TMP_DB="${BACKUP_DIR}/.steel_market-${STAMP}.dump.tmp"
TMP_CHROMA="${BACKUP_DIR}/.chroma-${STAMP}.tar.gz.tmp"
CONTAINER_DB="/tmp/steel-backup-${STAMP}.dump"
CONTAINER_CHROMA="/tmp/steel-chroma-${STAMP}.tar.gz"

cleanup() {
  rm -f "${TMP_DB}" "${TMP_CHROMA}"
  docker compose exec -T postgres rm -f "${CONTAINER_DB}" >/dev/null 2>&1 || true
  docker compose exec -T agent rm -f "${CONTAINER_CHROMA}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! docker compose exec -T postgres true >/dev/null 2>&1; then
  echo "postgres container is not running; start the stack first" >&2
  exit 1
fi

finalize() {
  local source_file="$1"
  local base_path="$2"
  local label="$3"
  openssl enc -aes-256-cbc -pbkdf2 -salt \
    -in "${source_file}" \
    -out "${base_path}.enc" \
    -pass env:BACKUP_PASSPHRASE
  rm -f "${source_file}"
  chmod 600 "${base_path}.enc"
  echo "${label}: ${base_path}.enc"
}

docker compose exec -T postgres pg_dump -U steel_agent -d steel_market -Fc -f "${CONTAINER_DB}"
docker compose cp "postgres:${CONTAINER_DB}" "${TMP_DB}"

docker compose exec -T agent tar -czf "${CONTAINER_CHROMA}" -C /app chroma_data
docker compose cp "agent:${CONTAINER_CHROMA}" "${TMP_CHROMA}"

finalize "${TMP_DB}" "${BACKUP_DIR}/steel_market-${STAMP}.dump" "database backup"
finalize "${TMP_CHROMA}" "${BACKUP_DIR}/chroma-${STAMP}.tar.gz" "chroma backup"

find "${BACKUP_DIR}" -maxdepth 1 -type f \
  \( -name 'steel_market-*.dump.enc' -o -name 'chroma-*.tar.gz.enc' \) \
  -mtime +"${BACKUP_KEEP_DAYS}" -print -delete
