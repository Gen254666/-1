#!/usr/bin/env bash
set -euo pipefail
umask 077

BACKUP_DIR="${BACKUP_DIR:-./backups}"
DATABASE_URL="${DATABASE_URL_AGENT:-}"
CHROMA_PATH="${CHROMA_PATH:-./data/chroma}"
BACKUP_PASSPHRASE="${BACKUP_PASSPHRASE:-}"
BACKUP_ALLOW_PLAINTEXT="${BACKUP_ALLOW_PLAINTEXT:-0}"

if [[ -z "${DATABASE_URL}" ]]; then
  echo "DATABASE_URL_AGENT is required (use postgresql:// not postgresql+asyncpg://)" >&2
  exit 1
fi

if [[ -z "${BACKUP_PASSPHRASE}" && "${BACKUP_ALLOW_PLAINTEXT}" != "1" ]]; then
  echo "BACKUP_PASSPHRASE is required (set BACKUP_ALLOW_PLAINTEXT=1 only for local dev)" >&2
  exit 1
fi

if [[ -n "${BACKUP_PASSPHRASE}" ]]; then
  if (( ${#BACKUP_PASSPHRASE} < 32 )) || [[ "${BACKUP_PASSPHRASE}" == CHANGE_ME* ]]; then
    echo "BACKUP_PASSPHRASE must be at least 32 characters and not a placeholder" >&2
    exit 1
  fi
fi

if [[ -n "${BACKUP_PASSPHRASE}" ]] && ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required for encrypted backups" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"
STAMP="$(date +%Y%m%d-%H%M%S)"
TMP_DB="${BACKUP_DIR}/.steel_market-${STAMP}.dump.tmp"
TMP_CHROMA="${BACKUP_DIR}/.chroma-${STAMP}.tar.gz.tmp"

cleanup() {
  rm -f "${TMP_DB}" "${TMP_CHROMA}"
}
trap cleanup EXIT

finalize() {
  local source_file="$1"
  local base_path="$2"
  local label="$3"
  if [[ -n "${BACKUP_PASSPHRASE}" ]]; then
    openssl enc -aes-256-cbc -pbkdf2 -salt \
      -in "${source_file}" \
      -out "${base_path}.enc" \
      -pass env:BACKUP_PASSPHRASE
    rm -f "${source_file}"
    chmod 600 "${base_path}.enc"
    echo "${label} (encrypted): ${base_path}.enc"
  else
    mv "${source_file}" "${base_path}"
    chmod 600 "${base_path}"
    echo "${label} (plaintext dev): ${base_path}"
  fi
}

PG_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"
pg_dump "${PG_URL}" -Fc -f "${TMP_DB}"
finalize "${TMP_DB}" "${BACKUP_DIR}/steel_market-${STAMP}.dump" "database backup"

if [[ -d "${CHROMA_PATH}" ]]; then
  tar -czf "${TMP_CHROMA}" -C "$(dirname "${CHROMA_PATH}")" "$(basename "${CHROMA_PATH}")"
  finalize "${TMP_CHROMA}" "${BACKUP_DIR}/chroma-${STAMP}.tar.gz" "chroma backup"
fi
