from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


compose: dict[str, Any] = yaml.safe_load(read("docker-compose.yml"))
services: dict[str, Any] = compose.get("services", {})
check(
    set(services) == {"postgres", "redis", "mcp-server", "agent", "frontend"},
    "compose services mismatch",
)

postgres = services.get("postgres", {})
redis = services.get("redis", {})
mcp = services.get("mcp-server", {})
agent = services.get("agent", {})
frontend = services.get("frontend", {})

check(str(postgres.get("image", "")).startswith("postgres:16"), "postgres image must be 16")
check("pgdata:/var/lib/postgresql/data" in postgres.get("volumes", []), "pgdata volume missing")
check(
    "./deploy/init_db.sh:/docker-entrypoint-initdb.d/10-init.sh:ro"
    in postgres.get("volumes", []),
    "init_db.sh mount missing",
)
check(str(redis.get("image", "")).startswith("redis:7"), "redis image must be 7")

for name, service in (("mcp-server", mcp), ("agent", agent)):
    build = service.get("build", {})
    check(build.get("dockerfile") == "backend/Dockerfile", f"{name} Dockerfile mismatch")
    check(build.get("context") == ".", f"{name} build context mismatch")

agent_command = " ".join(agent.get("command", []))
check("--proxy-headers" in agent_command, "agent must trust proxy headers")
check("mcp-server" in agent.get("depends_on", {}), "agent must depend on mcp-server")
check("chroma:/app/chroma_data" in mcp.get("volumes", []), "chroma volume missing")

frontend_build = frontend.get("build", {})
check(
    frontend_build.get("dockerfile") == "frontend/Dockerfile",
    "frontend Dockerfile mismatch",
)
frontend_ports = [str(port) for port in frontend.get("ports", [])]
check(any(port.endswith(":80") for port in frontend_ports), "frontend container port 80 missing")

env_text = " ".join(
    str(value)
    for service in services.values()
    for value in (service.get("environment") or {}).values()
)
for secret in ("${AGENT_DB_PASSWORD", "${MCP_DB_PASSWORD", "${JWT_SECRET", "${MCP_SERVICE_SECRET"):
    check(secret in env_text, f"secret placeholder missing: {secret}")

backend_dockerfile = read("backend/Dockerfile")
check(
    "uv sync --frozen --no-dev --extra rag" in backend_dockerfile,
    "backend Dockerfile sync command mismatch",
)
check("uvicorn" in backend_dockerfile, "backend Dockerfile CMD missing uvicorn")

frontend_dockerfile = read("frontend/Dockerfile")
check("npm ci" in frontend_dockerfile, "frontend Dockerfile npm ci missing")
check("npm run build" in frontend_dockerfile, "frontend Dockerfile build missing")

nginx = read("frontend/nginx.conf")
check("proxy_pass http://agent:8000;" in nginx, "nginx must proxy /api to agent")
check("proxy_buffering off;" in nginx, "nginx SSE buffering must be off")

init_db = read("deploy/init_db.sh")
check("CREATE ROLE steel_mcp" in init_db, "init_db.sh must create steel_mcp")
check("ALTER DEFAULT PRIVILEGES" in init_db, "init_db.sh must grant default SELECT")

dockerignore = read(".dockerignore")
for pattern in (".env", ".venv", "node_modules", ".superpowers"):
    check(pattern in dockerignore, f".dockerignore missing {pattern}")

for script in ("deploy/init_db.sh", "scripts/backup.sh"):
    data = (ROOT / script).read_bytes()
    check(b"\r\n" not in data, f"{script} must use LF line endings")

if errors:
    print("deployment validation failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("deployment validation passed: compose, Dockerfiles, nginx, init script, ignore rules")
