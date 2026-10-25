# 钢材行情智能体

面向云贵川钢材贸易的行情分析智能体 MVP：每日导入库存与报价，支持对话查价、价差与异动分析、报价单和日报。

## 当前状态

MVP 主要模块已完成：数据导入/版本回滚、行情查询、报价与日报、MCP 工具、Agent 对话和 React 前端。Docker 部署已在本机验证通过。

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

### Playwright E2E

前置条件：PostgreSQL 与 Memurai/Redis 已启动，`.env` 已配置 LLM Key，且至少导入过一天的报价数据。

```bash
cd frontend
npx playwright install chromium
npm run e2e
```

E2E 会自动启动 MCP、Agent 和 Vite，创建临时用户 `e2e_user`，覆盖登录、看板、智能对话、MCP 工具调用与报价卡片渲染。该用例依赖真实 LLM，默认不进入 CI。

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

开发环境默认管理员为 `admin` / `ChangeMe123!`，首次登录会被强制跳转到改密页，修改成功后才能访问其他功能。生产环境通过 `INITIAL_ADMIN_PASSWORD` 注入初始密码。

## 环境变量

```bash
cp .env.example .env
```

按实际环境填写 PostgreSQL 双账号、Redis、JWT 与 LLM Key。生产环境禁止使用默认密钥。

## 业务数据校验

每日上传库存 Excel 前先做一次校验：

```bash
cd backend
uv run python ../scripts/validate_business_data.py \
  --inventory "../10.25库存状况表（部分价格已调）.xlsx" \
  --date 2026-10-25
```

校验会输出库存行数、唯一规格、重复规格、缺单价/缺支重规格、可报价规格数和点位编码结果。

校验通过后，在前端“管理 → 导入数据”上传库存 Excel。系统会自动创建/更新方管、矩管点位，并用库存单价生成当日行情，不需要再手工填写 Mysteel 报价 CSV。部分规格缺单价时仍会建点位但不生成行情；缺支重的规格可以展示行情，但不能生成客户报价。

### 行情点位与自动报价

- 公共点位由库存规格自动生成：编码包含规格与长度，同一规格多行时取支数最多的一行。
- 每次库存导入自动生成当日报价版本；重复导入不会产生重复版本。
- 回滚库存批次后，系统会从恢复后的库存快照重新推导点位和行情。
- 自动生成的行情批次在管理页可见，但不能单独回滚，请回滚对应库存批次。
- 报价页的规格下拉直接来自当前库存，按方管/矩管分组并支持搜索。

已部署环境如需从现有库存快照补生成点位和行情：

```bash
cd backend
uv run python ../scripts/sync_inventory_points.py --date 2026-10-25
```

Docker 环境下：

```bash
docker compose exec -T agent python -m steel_core.cli.sync_inventory --date 2026-10-25
```

## Docker 部署

```bash
cp .env.example .env
# 填写 AGENT_DB_PASSWORD、MCP_DB_PASSWORD、JWT_SECRET、MCP_SERVICE_SECRET、LLM Key

docker compose up -d postgres redis
docker compose run --rm agent alembic upgrade head
docker compose run --rm agent python -m steel_core.db.seed
docker compose up -d
```

访问 `http://localhost:8080`（可通过 `.env` 的 `FRONTEND_PORT` 调整）。MCP Server 监听内部端口 8001，Agent 8000，Chroma 数据在 `chroma` 卷。

部署前可先做静态校验（无需 Docker）：

```bash
cd backend
uv run python ../scripts/validate_deploy.py
```

> 本机已在 Windows 11 + Docker Desktop（WSL2）完成实际部署验证：镜像构建、迁移、种子、前端/健康检查/登录冒烟均通过。前端默认映射 8080，端口 80 被占用时可通过 `.env` 的 `FRONTEND_PORT` 调整。RAG 嵌入模型首次使用会从 `HF_ENDPOINT`（默认 hf-mirror）下载，并已禁用 Xet 以避免镜像源 401。

### 生产部署（公司内部多人）

1. 生成强随机密钥并写入独立 env 文件：

```bash
python scripts/generate_secrets.py --write .env.prod
chmod 600 .env.prod
```

2. 在 `.env.prod` 中补充：`ENVIRONMENT=prod`、`APP_DOMAIN=你的域名`、`CORS_ORIGINS=["https://你的域名"]`、`AGENT_WORKERS=2`、DeepSeek/其他 LLM Key，以及 `BACKUP_PASSPHRASE`。
3. 用生产 overlay 启动（Caddy 自动申请/续期 TLS 证书，仅暴露 80/443）：

```bash
docker compose --env-file .env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml run --rm agent alembic upgrade head
docker compose --env-file .env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml run --rm \
  -e INITIAL_ADMIN_PASSWORD='首次管理员强密码' agent python -m steel_core.db.seed
```

4. 访问 `https://你的域名`。PostgreSQL、Redis、Agent、MCP 均不直接暴露到公网。
5. 上线检查：确认 `.env.prod` 权限 600、JWT/MCP 密钥非默认、CORS 只含正式域名、备份已加密并做一次恢复演练、监控磁盘与 `/readyz`、为管理员配置 LLM 每日额度。

安全默认值：登录失败 5 次锁定 15 分钟、会话空闲 60 分钟登出、对话 20 次/分钟、数据接口 120 次/分钟、导入 5 次/分钟、每用户每日 LLM 请求 200 次；均可在 `.env` 调整。导入和回滚必须二次确认并带 `confirm=true`。

### 密钥轮换

`.env.prod` 不提交到仓库、权限保持 600，应用和接口均不返回密钥。建议每 90 天或人员变动时轮换：

1. 用 `python scripts/generate_secrets.py` 生成新值，只替换需要轮换的项。
2. `JWT_SECRET` / `MCP_SERVICE_SECRET`：更新 `.env.prod` 后重启 agent 与 mcp-server；所有现有登录会话会被强制失效，用户需重新登录。
3. 数据库密码：在 PostgreSQL 执行 `ALTER ROLE steel_agent PASSWORD '...'`（`steel_mcp` 同理），同步更新 `.env.prod` 的 `AGENT_DB_PASSWORD` / `MCP_DB_PASSWORD`，再重启相关容器。
4. LLM Key：在厂商控制台先创建新 Key、更新 `.env.prod`、重启 agent，确认可用后再禁用旧 Key。
5. `BACKUP_PASSPHRASE`：新备份使用新口令；旧备份仍需旧口令解密，保留旧口令直到旧备份过保留期。
6. 轮换后验证 `/readyz`、登录、一次库存导入（先取消确认）和一次 MCP 对话。

## 备份与恢复

生产备份必须设置加密口令；备份目录 0700、文件 0600：

```bash
export DATABASE_URL_AGENT=postgresql://steel_agent:密码@localhost:5432/steel_market
export CHROMA_PATH=./data/chroma
export BACKUP_PASSPHRASE='使用强随机口令'
./scripts/backup.sh
```

本地开发如需明文备份，显式设置 `BACKUP_ALLOW_PLAINTEXT=1`，不要用于生产。

解密并恢复数据库：

```bash
openssl enc -d -aes-256-cbc -pbkdf2 \
  -in backups/steel_market-<时间戳>.dump.enc \
  -out backups/steel_market-<时间戳>.dump \
  -pass env:BACKUP_PASSPHRASE
pg_restore -d "$DATABASE_URL" backups/steel_market-<时间戳>.dump
```

恢复 Chroma：先按同样方式解密 `backups/chroma-<时间戳>.tar.gz.enc`，再解压到 `CHROMA_PATH` 的父目录。

运行 `bash scripts/verify_backup.sh` 可验证加密、解密和权限逻辑。

## 知识库

管理员进入「管理后台 → 知识库」，上传 Markdown / TXT / PDF / DOCX 文档，填写标题、类型、生效和过期日期。文档经 `bge-small-zh-v1.5` 本地向量化后写入 Chroma，对话中可通过 `search_knowledge` 检索并返回带 `[n]` 的引用。

- 首次入库会自动下载嵌入模型，国内网络通过 `HF_ENDPOINT=https://hf-mirror.com` 加速
- 过期文档默认不参与检索，管理员可在工具调用时显式包含
- 私有知识库集合结构已预留，本期仅开放公共知识库

## 我的点位与私有报价

普通用户在「我的点位」页面创建自定义私有点位（品类、规格、地区），并按日期录入价格、涨跌和备注。私有报价使用独立的按用户版本链，不会覆盖公共行情，也不会被其他用户或管理员读取。

- 报价按 `(用户, 日期)` 维护版本，重复录入会生成新版本并保留历史
- 私有报价只对本人可见；公共看板仍展示公共点位
- 可在同一页面查看私有点位的最新报价

## 设计文档

- 规格：`docs/superpowers/specs/2026-10-23-steel-market-agent-design.md`
- 实现计划：`实现计划.txt`
