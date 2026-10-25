#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin"
cat > "$TMP/bin/pg_dump" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f)
      out="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
printf 'backup-test-content' > "$out"
SH
chmod +x "$TMP/bin/pg_dump"

export PATH="$TMP/bin:$PATH"
export DATABASE_URL_AGENT="postgresql://steel_agent:test@localhost:5432/steel_market"
export BACKUP_DIR="$TMP/backups"
export CHROMA_PATH="$TMP/no-chroma"
export BACKUP_PASSPHRASE="test-passphrase-0123456789abcdef-strong"
unset BACKUP_ALLOW_PLAINTEXT || true

bash "$ROOT/scripts/backup.sh"

enc="$(ls "$BACKUP_DIR"/steel_market-*.dump.enc | head -1)"
[[ -f "$enc" ]] || { echo "encrypted backup missing"; exit 1; }
[[ ! -e "${enc%.enc}" ]] || { echo "plaintext backup still present"; exit 1; }

dec="$TMP/decrypted.dump"
openssl enc -d -aes-256-cbc -pbkdf2 -in "$enc" -out "$dec" -pass env:BACKUP_PASSPHRASE
cmp -s <(printf 'backup-test-content') "$dec" || { echo "decrypt mismatch"; exit 1; }

case "$(uname -s)" in
  MINGW*|MSYS*)
    echo "permission check skipped on Windows"
    ;;
  *)
    [[ "$(stat -c '%a' "$enc")" == "600" ]] || { echo "backup permissions not 600"; exit 1; }
    ;;
esac

set +e
env -u BACKUP_PASSPHRASE -u BACKUP_ALLOW_PLAINTEXT bash "$ROOT/scripts/backup.sh" >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -ne 0 ]] || { echo "backup without passphrase must fail"; exit 1; }

set +e
BACKUP_PASSPHRASE=short bash "$ROOT/scripts/backup.sh" >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -ne 0 ]] || { echo "weak passphrase must fail"; exit 1; }

set +e
BACKUP_PASSPHRASE=CHANGE_ME_please_replace_this_value_123456 bash "$ROOT/scripts/backup.sh" >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -ne 0 ]] || { echo "placeholder passphrase must fail"; exit 1; }

echo "backup verification passed"
