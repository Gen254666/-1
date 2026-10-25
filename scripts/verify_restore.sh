#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export MSYS_NO_PATHCONV=1
BACKUP_DIR="${BACKUP_DIR:-./backups}"

PASS="${BACKUP_PASSPHRASE:-}"
if [[ -z "$PASS" && -f .env ]]; then
  PASS="$(grep -m1 '^BACKUP_PASSPHRASE=' .env | cut -d= -f2- | tr -d '\r"')"
fi
if [[ -z "$PASS" ]]; then
  echo "BACKUP_PASSPHRASE is required" >&2
  exit 1
fi

DB_ENC="$(ls -1t "${BACKUP_DIR}"/steel_market-*.dump.enc 2>/dev/null | head -1 || true)"
CHROMA_ENC="$(ls -1t "${BACKUP_DIR}"/chroma-*.tar.gz.enc 2>/dev/null | head -1 || true)"
if [[ -z "$DB_ENC" || -z "$CHROMA_ENC" ]]; then
  echo "encrypted backups not found in ${BACKUP_DIR}; run backup first" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
TMP="$(mktemp -d "${BACKUP_DIR}/.restore-XXXXXX")"
STAMP="$(date +%s)"
TEMP_DB="steel_market_restore_${STAMP}"
CONTAINER_DUMP="/tmp/restore-check-${STAMP}.dump"

cleanup() {
  docker compose exec -T postgres dropdb --if-exists -U steel_agent "$TEMP_DB" >/dev/null 2>&1 || true
  docker compose exec -T postgres rm -f "$CONTAINER_DUMP" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "stage: decrypt"
export BACKUP_PASSPHRASE="$PASS"
openssl enc -d -aes-256-cbc -pbkdf2 -in "$DB_ENC" -out "$TMP/restore.dump" -pass env:BACKUP_PASSPHRASE
openssl enc -d -aes-256-cbc -pbkdf2 -in "$CHROMA_ENC" -out "$TMP/chroma.tar.gz" -pass env:BACKUP_PASSPHRASE

echo "stage: createdb"
docker compose exec -T postgres createdb -U steel_agent "$TEMP_DB"
echo "stage: copy dump"
docker compose cp "$TMP/restore.dump" "postgres:${CONTAINER_DUMP}"
echo "stage: pg_restore"
docker compose exec -T postgres pg_restore -U steel_agent -d "$TEMP_DB" "$CONTAINER_DUMP"

echo "stage: counts"
counts() {
  docker compose exec -T postgres psql -U steel_agent -d "$1" -tAc \
    "select (select count(*) from price_point) || ',' || (select count(*) from market_quote) || ',' || (select count(*) from inventory_item)" \
    | tr -d '\r'
}
PROD_COUNTS="$(counts steel_market)"
RESTORED_COUNTS="$(counts "$TEMP_DB")"
if [[ "$PROD_COUNTS" != "$RESTORED_COUNTS" ]]; then
  echo "restore count mismatch: production=${PROD_COUNTS} restored=${RESTORED_COUNTS}" >&2
  exit 1
fi

echo "stage: chroma"
BACKUP_FILES="$(tar -tzf "$TMP/chroma.tar.gz" | awk '!/\/$/' | wc -l | tr -d ' ')"
LIVE_FILES="$(docker compose exec -T agent sh -c 'find /app/chroma_data -type f | wc -l' | tr -d '\r ')"
if [[ "$BACKUP_FILES" != "$LIVE_FILES" ]]; then
  echo "chroma file count mismatch: backup=${BACKUP_FILES} live=${LIVE_FILES}" >&2
  exit 1
fi

echo "restore verification passed"
echo "database counts (points,quotes,inventory): ${PROD_COUNTS}"
echo "chroma files: ${LIVE_FILES}"
