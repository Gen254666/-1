from __future__ import annotations

import argparse
import secrets
import stat
import sys
from pathlib import Path

SECRET_KEYS = (
    "AGENT_DB_PASSWORD",
    "MCP_DB_PASSWORD",
    "JWT_SECRET",
    "MCP_SERVICE_SECRET",
    "BACKUP_PASSPHRASE",
)


def generate_secrets() -> dict[str, str]:
    return {key: secrets.token_urlsafe(48) for key in SECRET_KEYS}


def render(values: dict[str, str]) -> str:
    lines = ["# generated secrets — keep this file private (chmod 600)"]
    lines.extend(f"{key}={value}" for key, value in values.items())
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="生成生产环境强随机密钥")
    parser.add_argument("--write", type=Path, default=None, help="写入指定 env 文件")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的文件")
    args = parser.parse_args()

    values = generate_secrets()
    if args.write is None:
        print(render(values), end="")
        return 0

    path: Path = args.write
    if path.exists() and not args.force:
        print(f"拒绝覆盖已存在文件: {path}（使用 --force 覆盖）", file=sys.stderr)
        return 1
    path.write_text(render(values), encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"已写入 {path}（权限 600）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
