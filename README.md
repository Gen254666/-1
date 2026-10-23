# 钢材行情智能体

面向云贵川钢材贸易的行情分析智能体 MVP：每日导入库存与报价，支持对话查价、价差与异动分析、报价单和日报。

## 当前状态

MVP 主要模块已完成：数据导入/版本回滚、行情查询、报价与日报、MCP 工具、Agent 对话和 React 前端。集成回归与部署演练进行中。

## 目录结构

```
backend/          FastAPI Agent、steel_core 领域层、MCP Server
frontend/         React + TypeScript
config/           Prompt、免责文案、默认阈值
data/             导入文件与导出（业务数据不入库）
knowledge/        公共知识库文档
docs/             设计规格与计划
```

## 本地开发

```bash
cd backend
uv sync --extra dev --extra rag
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

### 前端

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173，/api 代理到 8000
npm test
npm run build
```

### 本地 PostgreSQL（Windows 开发）

本机使用 `pgserver` 自带的 PostgreSQL 16 二进制，数据目录放在英文路径，端口 `55432`：

```bash
PG_ROOT="$LOCALAPPDATA/steel-market-pg"
"$PG_ROOT/pginstall/bin/pg_ctl.exe" -D "$PG_ROOT/data" start
"$PG_ROOT/pginstall/bin/pg_ctl.exe" -D "$PG_ROOT/data" stop
```

`.env` 中的 `DATABASE_URL_AGENT` / `DATABASE_URL_MCP` 指向该实例。生产环境使用标准 PostgreSQL，不使用此开发集群。

首次初始化：

```bash
cd backend
uv run alembic upgrade head
uv run python -m steel_core.db.seed
```

开发环境默认管理员为 `admin` / `ChangeMe123!`，首次登录必须修改。生产环境通过 `INITIAL_ADMIN_PASSWORD` 注入初始密码。

## 环境变量

```bash
cp .env.example .env
```

按实际环境填写 PostgreSQL 双账号、Redis、JWT 与 LLM Key。生产环境禁止使用默认密钥。

## Docker 部署

```bash
cp .env.example .env
# 填写 AGENT_DB_PASSWORD、MCP_DB_PASSWORD、JWT_SECRET、MCP_SERVICE_SECRET、LLM Key

docker compose up -d postgres redis
docker compose run --rm agent alembic upgrade head
docker compose run --rm agent python -m steel_core.db.seed
docker compose up -d
```

访问 `http://localhost`。MCP Server 监听内部端口 8001，Agent 8000，Chroma 数据在 `chroma` 卷。

> 当前开发机未安装 Docker，因此 compose 未实际运行；本地开发请用上面的 pgserver 方案。

## 备份与恢复

```bash
export DATABASE_URL_AGENT=postgresql://steel_agent:密码@localhost:5432/steel_market
export CHROMA_PATH=./data/chroma
./scripts/backup.sh
```

恢复数据库：

```bash
pg_restore -d "$DATABASE_URL" backups/steel_market-<时间戳>.dump
```

恢复 Chroma：解压 `backups/chroma-<时间戳>.tar.gz` 到 `CHROMA_PATH` 的父目录即可。

## 知识库

管理员进入「管理后台 → 知识库」，上传 Markdown / TXT / PDF / DOCX 文档，填写标题、类型、生效和过期日期。文档经 `bge-small-zh-v1.5` 本地向量化后写入 Chroma，对话中可通过 `search_knowledge` 检索并返回带 `[n]` 的引用。

- 首次入库会自动下载嵌入模型，国内网络通过 `HF_ENDPOINT=https://hf-mirror.com` 加速
- 过期文档默认不参与检索，管理员可在工具调用时显式包含
- 私有知识库集合结构已预留，本期仅开放公共知识库

## 设计文档

- 规格：`docs/superpowers/specs/2026-10-23-steel-market-agent-design.md`
- 实现计划：`实现计划.txt`
