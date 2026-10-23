# 钢材行情智能体 设计规格

- 日期：2026-10-23
- 状态：待评审
- 范围：国内贸易 MVP（云贵川）；出口贸易为二期
- 数据源：Mysteel 网页会员（人工整理 CSV 导入）+ 每日库存 Excel（昆明宝象库）

## 1. 背景与目标

公司为钢材贸易商，并拥有自有管材加工厂，主营方管、矩管、圆管，兼营型材、板材、线材；市场以云贵川为主，另有缅甸、老挝、越南边境出口业务。

MVP 目标：

- 每日导入库存与报价，形成可查询的历史行情
- 对话式查价、走势、价差与异动
- 快速生成带来源和免责声明的报价单
- 自动生成每日行情日报
- 支持多用户使用，数据隔离可审计

非目标：

- 自动抓取 Mysteel 网页（违反会员条款、封号风险，且不做风控规避）
- 出口报价、境内外价差、汇率（二期）
- 对外 SaaS 多租户（单公司内部多用户）
- 行情平台 API 自动拉取、定时日报（迭代项）

## 2. 用户与权限

角色仅两种：`admin`、`user`。

| 操作             | admin    | user |
| -------------- | -------- | ---- |
| 查看公共点位/行情/日报   | 是        | 是    |
| 维护公共点位         | 是        | 否    |
| 私有点位增删改查       | 仅本人      | 仅本人  |
| 查看他人私有点位       | 否（默认不可读） | 否    |
| 导入库存/报价、回滚     | 是        | 否    |
| 生成日报           | 是        | 否    |
| 知识库上传/删除       | 是        | 否    |
| 检索公共知识库        | 是        | 是    |
| 用户管理、异常阈值、系统状态 | 是        | 否    |
| 对话、会话、报价单      | 仅本人      | 仅本人  |

权限在 FastAPI 依赖层与 MCP 用户上下文层双重执行。

## 3. 总体架构

```
React 前端 ──SSE/REST──> FastAPI Agent ──MCP over Streamable HTTP──> MCP Server
(对话/卡片/图表)     (JWT/限流/熔断/编排)   (签名短时JWT携带用户上下文)   (工具/计算/图表JSON)
                              │                                          │
                    ┌─────────┼─────────┐                     ┌──────────┼──────────┐
                PostgreSQL   Redis   外部 LLM(httpx)      PostgreSQL   ChromaDB   外部数据(httpx,迭代)
              (用户/点位/报价/版本)  (会话/限流/缓存/熔断)   (同一实例)    (内嵌持久化)    (期货等公开数据)
```

- 生产链路全程 HTTP，使用 MCP Streamable HTTP；MCP Studio/Inspector 仅用于本地调试。
- Agent 每次调用 MCP 携带签名的短时 JWT（`user_id`、角色、可见范围，TTL 60 秒，audience=mcp-server），MCP 中间件校验后注入用户上下文。
- 计算集中在 `steel_core`，MCP Server 与 REST 共用；LLM 只做意图判断与文字总结。
- MCP 工具只读；所有写操作走 REST + 前端 UI。
- 数据库最小权限隔离：Agent 使用全量读写账号；MCP Server 使用只读账号，仅授予所需表的 SELECT 权限，写操作由数据库层直接拒绝。

## 4. 技术栈

- 后端：Python 3.11+，FastAPI，httpx（异步外部请求），Pydantic v2，SQLAlchemy 2.0 async + asyncpg，Alembic
- 智能体协议：MCP（Streamable HTTP）；MCP Server 使用 FastMCP
- 数据库：PostgreSQL 16；时序表结构预留 TimescaleDB 迁移
- 缓存/会话/限流：Redis 7
- 图表：服务端输出原始序列 + 图表配置，前端 Plotly 适配层渲染
- LLM：Claude、DeepSeek、豆包兼容 API；httpx 直连适配
- RAG：LangChain + ChromaDB（持久化内嵌），fastembed + `BAAI/bge-small-zh-v1.5`
- 前端：React + TypeScript + Vite + Ant Design + react-plotly.js
- 测试：pytest / pytest-asyncio / Vitest / Playwright
- 部署：docker-compose（postgres、redis、mcp-server、agent、frontend）
- 版本管理：Git + Conventional Commits + SemVer + CHANGELOG

## 5. 数据模型

### 5.1 账号与会话

`users`

- `id` UUID PK，`username` unique，`password_hash`（argon2），`role`（admin/user），`is_active`，`failed_login_count`，`locked_until`，`created_at`，`updated_at`

`user_session`

- `id` UUID PK，`user_id` FK，`refresh_token_hash` unique，`device`，`ip`，`user_agent`，`expires_at`，`revoked_at`，`rotated_from`，`created_at`

`chat_session`

- `id`，`user_id`，`title`，`created_at`，`updated_at`，`archived`

`chat_message`

- `id`，`session_id`，`role`（user/assistant/tool），`content`，`artifacts` jsonb，`tool_calls` jsonb，`created_at`

### 5.2 行情点位与报价

`price_point`

- `id` UUID PK，`scope`（public/private），`owner_user_id`（public 为 NULL），`code`，`category`，`spec`，`region`，`source`，`unit`，`is_active`，`created_at`
- 约束：public 必须 `owner_user_id IS NULL`；private 必须非空
- 索引：public 部分唯一索引 `(code) WHERE scope='public'`；private 唯一索引 `(owner_user_id, code) WHERE scope='private'`

`market_quote`

- `id`，`version_id` FK，`point_id` FK，`quote_date`，`price` numeric(12,2)，`change` numeric(12,2) NULL，`source`，`note`，`created_at`
- 唯一索引 `(version_id, point_id, quote_date)`
- 查询按 `(dataset_type='market_quote', effective_date)` 的 active 版本取数
- 未来可将 `quote_date` 转为 TimescaleDB hypertable

### 5.3 库存

`inventory_snapshot`

- `id`，`version_id` FK，`snapshot_date`，`warehouse`（默认"昆明宝象库"），`source_file`，`imported_at`

`inventory_item`

- `id`，`snapshot_id` FK，`block`（方管/矩形管/其他），`spec`，`unit_price`，`tax_add`，`weight_per_piece`，`pieces`，`total_weight`，`price_per_piece`，`packaging`，`manufacturer`，`row_no`

### 5.4 导入与版本

`import_batch`

- `id`，`user_id`，`dataset_type`（market_quote/inventory），`effective_date`，`file_name`，`file_hash`，`status`（success/failed/rolled_back），`rows_total`，`rows_ok`，`rows_failed`，`errors` jsonb，`created_at`，`rolled_back_at`

`dataset_version`

- `id`，`dataset_type`，`effective_date`，`version_no`，`status`（active/superseded/rolled_back），`import_batch_id`，`checksum`，`created_at`
- 唯一索引 `(dataset_type, effective_date, version_no)`
- 同一日期仅一个 active 版本：部分唯一索引 `(dataset_type, effective_date) WHERE status='active'`
- 默认保留最近 10 个版本

### 5.5 日报与配置

`daily_report`

- `id`，`report_date`，`version_no`，`markdown`，`sources` jsonb，`disclaimer`，`model`，`created_by`，`created_at`
- 同一 `report_date` 可保留多个版本，查询默认返回最新版本；仅 admin 可生成

`app_config`

- `key` PK，`value` jsonb，`updated_by`，`updated_at`
- 存放异常阈值、免责文案、报价口径等配置

`audit_log`

- `id`，`user_id`，`action`，`resource_type`，`resource_id`，`detail` jsonb，`ip`，`created_at`

### 5.6 知识库元数据（Chroma）

`doc_id`、`title`、`doc_type`（policy/industry/terminology/report/internal_rule）、`collection`、`source`、`effective_date`、`expire_ts`、`expire_date`、`content_hash`、`chunk_index`

- `expire_ts`（Unix 时间戳，整数）仅用于检索过滤；`expire_date`（YYYY-MM-DD）仅用于前端展示与后台管理；两者由同一有效期字段派生

## 6. 公共跟踪点位（种子数据）

| #  | 品类    | 规格             | 地区 |
| -- | ----- | -------------- | -- |
| 1  | 方管    | 100×100×2.5×6m | 昆明 |
| 2  | 方管    | 150×150×3.0×6m | 昆明 |
| 3  | 矩管    | 100×150×2.5×6m | 昆明 |
| 4  | 矩管    | 100×200×3.0×6m | 昆明 |
| 5  | 圆管/焊管 | 4寸×3.75        | 昆明 |
| 6  | 镀锌管   | 4寸×3.75        | 昆明 |
| 7  | 角钢    | 50×5           | 昆明 |
| 8  | 槽钢    | 16#            | 昆明 |
| 9  | H型钢   | 300×300        | 昆明 |
| 10 | 中厚板   | 20mm           | 昆明 |
| 11 | 热卷    | 4.75×1500×C    | 昆明 |
| 12 | 高线    | Φ8             | 昆明 |
| 13 | 盘螺    | Φ8             | 昆明 |
| 14 | 螺纹钢   | HRB400E Φ20    | 昆明 |
| 15 | 热卷    | 4.75×1500×C    | 成都 |
| 16 | 螺纹钢   | HRB400E Φ20    | 贵阳 |

说明：

- 点位需核对 Mysteel 昆明/成都/贵阳频道是否有报价；无报价的替换为同品类可获取规格，点位数据存于数据库，可维护
- #11 热卷兼作方矩管原料成本参照，用于"管材-原料价差"
- 用户可创建私有自定义点位，MVP 由本人手工录入价格，不自动拉取

## 7. MCP Server

### 7.1 传输与鉴权

- Streamable HTTP；健康检查与内部知识库入库接口使用 FastMCP 自定义路由
- Agent → MCP 使用 HS256 短时服务 JWT（`user_id`、`role`、`aud`、`exp`）；MCP 中间件校验失败返回 `AUTH_TOKEN_INVALID` 或 `AUTH_TOKEN_EXPIRED`
- 工具可访问的数据范围由服务端上下文决定，不接受 LLM 或客户端传入的 `user_id`
- 工具级角色鉴权：`generate_daily_report` 仅 admin 可调用，普通用户直接返回 `PERMISSION_DENIED`，不执行计算
- MCP Server 使用 PostgreSQL 只读账号，最小权限隔离

### 7.2 工具清单

| 工具                      | 作用                     | artifact.type    |
| ----------------------- | ---------------------- | ---------------- |
| `get_meta`              | 数据字典、可用点位（含 ID）、最新数据日期 | text/table       |
| `get_quotes`            | 按日期/品类/地区查报价           | cards            |
| `get_price_history`     | 单点/多点历史走势与统计           | chart            |
| `compare_spread`        | 区域价差、品种价差              | chart            |
| `scan_anomalies`        | 涨跌幅、连续涨跌、库存异动          | table            |
| `get_inventory`         | 库存查询、昨日对比、低库存          | cards            |
| `generate_quote`        | 生成报价单（纯计算）             | quote            |
| `get_daily_report`      | 读取已存档日报                | report           |
| `generate_daily_report` | 生成日报事实稿（admin，不落库）     | report           |
| `search_knowledge`      | 知识库检索                  | text + citations |

### 7.3 统一入参

| 参数                      | 规则                                        |
| ----------------------- | ----------------------------------------- |
| `point_ids`             | 优先使用点位 ID；自然语言先经 `get_meta` 解析；歧义返回候选，不猜测 |
| `start_date`/`end_date` | 默认近 30 天；最大跨度 730 天；超限 `INVALID_ARGUMENT` |
| `page`/`page_size`      | 列表分页，默认 1/20，上限 100                       |
| `use_cache`             | 默认 true；私有数据缓存 key 必须含 `user_id`          |

### 7.4 统一返回

```json
{
  "summary": "给 LLM 的文字摘要",
  "artifact": { "type": "cards|chart|table|quote|report|text", "payload": {} },
  "meta": { "as_of": "2026-10-23", "source": "mysteel", "cached": true, "warnings": [] },
  "error": null
}
```

错误时 `artifact` 为 null：

```json
{ "code": "INVALID_ARGUMENT|NOT_FOUND|DATA_UNAVAILABLE|PERMISSION_DENIED|RATE_LIMITED|UPSTREAM_ERROR|TOOL_LIMIT_EXCEEDED|AUTH_TOKEN_INVALID|AUTH_TOKEN_EXPIRED",
  "message": "中文说明", "details": {}, "retryable": false }
```

### 7.5 图表契约

```json
{
  "series": [{ "name": "", "x": [], "y": [], "unit": "元/吨" }],
  "chart": { "kind": "line|bar|scatter", "title": "", "x_label": "", "y_label": "" },
  "meta": { "as_of": "" }
}
```

前端通过 Plotly 适配层渲染，MCP 输出不绑定绘图库。

### 7.6 溯源与免责

- `generate_quote` 返回 `sources[]`（点位 ID、报价日期、原始单价、库存快照日期、来源）、`disclaimer`、`valid_until`（当日）、`warnings[]`
- `generate_daily_report` 返回 `sources[]`、`as_of`、`disclaimer`
- 免责文案由 `app_config` 固定渲染，LLM 不得生成或改写
- 数据缺失时返回 `warnings`；系统提示禁止编造数字

## 8. FastAPI Agent

### 8.1 认证

- access token 30 分钟，存前端内存；refresh token 7 天，HttpOnly + Secure + SameSite=Strict Cookie
- refresh token 轮换；重复使用触发 `AUTH_REFRESH_REUSED`，吊销整条会话链
- 登录失败 5 次锁定 15 分钟（`AUTH_ACCOUNT_LOCKED`）
- 注销：refresh 会话吊销 + access `jti` 写入 Redis 黑名单

### 8.2 限流与熔断

- Redis 滑动窗口：登录 5 次/分钟/IP；对话 20 次/分钟/用户；数据接口 120 次/分钟/用户（可配）
- Redis 不可用时降级为进程内令牌桶并记录告警
- 每个 LLM 厂商独立熔断：5 次失败/60 秒打开，30 秒后半开；状态存 Redis
- 降级链可配：Claude → DeepSeek → 豆包；某家熔断只跳过该家
- 熔断状态变化写结构化日志与告警队列；可选 Webhook（企业微信/钉钉）
- 全部厂商失败：返回错误说明 + 看板最新数据，不中断服务

### 8.3 对话编排

```
鉴权 → 限流 → 载入会话历史 → LLM 判断意图并调用 MCP 工具
→ 合并结构化结果 → LLM 总结并流式输出 → 持久化消息与 artifacts
```

- `max_tool_rounds=4`（可配）：单个用户回合内"LLM 思考 → 调用工具"的循环轮数上限，触顶后强制收尾并提示"已停止继续查询"
- `max_tool_calls_per_turn=8`（可配）：单轮中允许并行发起的工具调用数量上限，超出的调用不执行，返回 `TOOL_LIMIT_EXCEEDED` 并在总结中说明
- 单工具超时 10 秒；工具失败不中断整轮，转述 `error.message`
- 系统提示：只能使用工具返回值、错误如实转述、引用使用 `[n]`、禁止编造

## 9. REST API

```
认证    POST /api/auth/login | /refresh | /logout
用户    GET/POST/PATCH /api/users                      (admin)
点位    GET/POST/PATCH/DELETE /api/points              (private 仅本人；public 仅 admin)
私有点报价 POST /api/points/{id}/quotes                (owner)
看板    GET  /api/dashboard?date=
行情    GET  /api/quotes | /api/history | /api/inventory
日报    GET  /api/reports | GET /api/reports/{date} | POST /api/reports/generate (admin)
报价    POST /api/quote/generate
对话    POST /api/chat/stream (SSE)
        POST /api/chat/sessions | GET /api/chat/sessions | GET /api/chat/sessions/{id}/messages
配置    GET/PUT /api/admin/config/anomaly
导入    POST /api/admin/import/inventory | /quotes
        GET  /api/admin/imports | POST /api/admin/imports/{batch_id}/rollback
知识库  POST /api/admin/knowledge/documents | DELETE /api/admin/knowledge/documents/{doc_id}
系统    GET  /api/admin/system/status | /metrics（内网）
运维    GET  /healthz | /readyz
```

`POST /api/quote/generate` 直连 `steel_core` 同步计算，不经过 LLM；对话内报价单走 MCP 工具链路，两者共用同一计算实现，结果必须一致。

SSE 事件：`token`、`tool_start`、`tool_end`、`artifact`、`warning`、`error`、`done`。

## 10. 前端

技术：React + TS + Vite + Ant Design + react-plotly.js（适配层）

1. 行情看板：当日报价卡片（按品类分组、涨红跌绿）、库存概览、异常提醒、最新日报
2. 智能对话：流式聊天、工具调用状态、内嵌卡片与交互图、会话历史
3. 报价单：表单（规格/数量/目的地/运费）→ 预览（含来源与免责）→ 导出 Markdown
4. 管理后台：导入与回滚记录、公共点位、用户管理、异常阈值、知识库文档、系统状态
5. 登录页与路由守卫；access token 内存保存，401 自动刷新一次

## 11. 数据导入

### 11.1 库存 Excel

- 文件：每日《库存状况表》，单 Sheet，左右两个区块：A-I 方管、J-R 矩形管
- 生效日期：导入时显式指定；未指定则从文件名解析（如 `10.23库存状况表.xlsx` → 当年 10 月 23 日；若晚于今天则回退到上一年），并与表尾打印日期交叉校验，不一致时返回 warning
- 表头行识别"规格型号/单价/含税加/支重/支数/重量/支售价/包装/厂家"；数据到"制表人"行为止
- 跳过空规格行；同规格重复行保留并记录行号
- 数值解析失败记入行级错误；整批事务失败则回滚
- 校验公式：`支售价 = 单价 × 支重 ÷ 1000`，偏差超过 0.05 时产生 warning
- 后续新增圆管/型材区块时，通过区块映射配置扩展

### 11.2 Mysteel 报价 CSV

- 模板列：`point_id, date(YYYY-MM-DD), price, change, source, note`
- 校验：点位存在且可见、日期合法、价格 > 0；缺少点位在结果中列出
- 私有点位报价由本人通过 REST 或 UI 录入

### 11.3 版本与回滚

- 导入创建新 `dataset_version`，旧版本置 `superseded`，新版本置 `active`，单事务完成
- `checksum` 与当前版本一致时提示"无变化"并跳过
- 回滚：`POST /api/admin/imports/{batch_id}/rollback`，当前版本置 `rolled_back`，上一版本恢复 `active`，不删除数据
- 导入与回滚写 `import_batch`、`audit_log`
- 导入成功后按日期失效 Redis 缓存


## 12. 计算规则

- 涨跌：优先使用导入的 `change`，缺失时按上一有效报价日期计算；同时输出涨跌幅
- 价差：按日期对齐计算 A-B；缺失日期剔除并返回 warning
- 统计：最新、最高、最低、均值、标准差、区间涨跌
- 异常（阈值存 `app_config`，无配置用默认值）：
  - 日涨跌幅超阈值（默认 2%）
  - 连续上涨/下跌天数（默认 3 天）
  - 库存相对 7 日均值偏离（默认 30%）
  - 低库存（支数低于阈值，默认 10）
- 报价单：`支售价 = 单价 × 支重 ÷ 1000`；`合计 = 支售价 × 支数 + 运费 + 加工费`；输出元/吨换算
- 含税口径：配置项，默认沿用库存表"单价直接计算支售价"，并在报价单标注待业务确认

## 13. RAG

- 集合：`kb_public`、`kb_private_<user_id>`（私有库本期只预留结构）
- 支持格式：Markdown/TXT/PDF/DOCX；元数据见 5.6
- 切分：中文递归切分（`\n\n`、`\n`、`。`、`；`），chunk 500-800 字，重叠 100 字
- 嵌入：fastembed + `BAAI/bge-small-zh-v1.5`（本地 ONNX，无需 torch）
- 去重：`content_hash`；更新先删旧 chunk 再入库
- 检索：服务端按用户解析可用集合；`collections` 仅为偏好提示
- 过期：检索过滤只使用 `expire_ts`（整数时间戳），`expire_date` 仅用于前端展示；默认过滤 `expire_ts < 今天`；未设置有效期的文档写入哨兵值（2100-01-01），保证过滤条件统一；管理员可 `include_expired=true`
- 引用：返回 `citations[]`，`summary` 使用 `[n]`；前端渲染来源脚注
- 写入：Chroma 持久化内嵌于 MCP Server；管理后台上传由 Agent 转发至 MCP Server 内部管理接口（服务令牌保护），避免多进程写入
- 预留：`reranker` 接口，MVP 为 no-op

## 14. 安全

- 上传白名单：`.xlsx`、`.csv`、`.pdf`、`.docx`、`.md`、`.txt`；拒绝 `.xlsm`/`.xls`
- 校验魔数/MIME；单文件 20MB；Excel 行数 10,000；解析超时
- 文件名 UUID 化；非 Web 根目录；临时目录解析；防路径穿越
- 压缩包解压大小与压缩比校验，防 zip bomb
- 导出 CSV 对 `= + - @` 开头单元格转义，防公式注入
- 密码 argon2；密钥仅环境变量；日志脱敏
- SQL 通过 ORM 参数化；所有输入经 Pydantic 校验
- 审计日志覆盖登录、导入、回滚、点位管理、用户管理、知识库操作
- 可选 ClamAV 扫描列为迭代

## 15. 可观测性

- `/metrics`：HTTP 请求数/耗时/状态码；LLM 调用数/首 token 延迟/错误/降级/熔断状态；MCP 工具调用数/耗时/错误/触顶次数；导入行数与失败数、最近成功导入时间；缓存命中率；Redis/PG 连接池
- 结构化 JSON 日志：`request_id`、`user_id`、工具名、耗时、错误码
- `/healthz` 存活；`/readyz` 检查 PG/Redis/MCP；`/api/admin/system/status` 展示依赖与熔断状态
- docker-compose 可选 `monitoring` profile（Prometheus + Grafana）

## 16. 错误处理与降级

| 场景        | 策略                                              |
| --------- | ----------------------------------------------- |
| 参数/业务错误   | 统一错误码，不抛 500                                    |
| LLM 上游失败  | 独立熔断 + 降级链；全部失败时返回数据与说明                         |
| MCP 不可用   | 对话返回 `UPSTREAM_ERROR`；REST 直连 `steel_core` 不受影响 |
| 数据上游超时    | 连接 5s、读取 30s；幂等 GET 重试 2 次；流式中断不重试              |
| Redis 不可用 | 关闭缓存；限流降级为进程内令牌桶；告警                             |
| 数据库失败     | 请求级事务；导入整批回滚；连接池健康检查                            |
| 工具失败      | 不中断对话，转述错误                                      |

## 17. 测试策略

- 单元：Excel 解析（fixture 用真实样例脱敏）、规格归一化、支售价公式（3550×24.93/1000=88.5）、价差、异常阈值、分页与时间跨度、错误结构
- 集成（PostgreSQL 容器 + fakeredis）：迁移、导入、查询全链路；权限矩阵逐行用例；私有数据跨用户越权；JWT 刷新/复用/吊销；限流；工具调用上限；快照回滚（数据与缓存恢复）；MCP 只读账号的写操作被数据库拒绝
- MCP 契约：入参/出参 schema、chart payload、错误码
- RAG：去重、过期过滤、引用格式、跨用户集合越权
- Agent：httpx MockTransport 模拟三家 LLM；工具循环；SSE 事件顺序；单厂商熔断不影响其他厂商；告警产生
- 上传安全：伪造扩展名、超大文件、zip bomb、宏文件、公式注入
- 前端：Vitest + Testing Library；Playwright 覆盖登录 → 看板 → 对话 → 报价单
- CI：ruff + mypy + pytest；eslint + tsc + vitest

## 18. 部署与运维

- docker-compose：postgres、redis、mcp-server、agent、frontend（nginx）；Chroma 数据卷挂载至 mcp-server
- MVP 阶段 mcp-server 单副本运行（Chroma 内嵌单写入进程）；扩容方案见 V2
- 本机开发：Python 3.11+、Node 20+、本地 PostgreSQL/Redis，可不用 Docker
- 数据库账号：迁移与业务写入使用 Agent 读写账号；MCP 只读账号仅授权 SELECT，由初始化脚本创建
- `.env.example`：DATABASE_URL_AGENT（读写）、DATABASE_URL_MCP（只读）、REDIS_URL、JWT_SECRET、MCP_BASE_URL、MCP_SERVICE_SECRET、LLM Keys、LLM_FALLBACK_ORDER、CORS_ORIGINS 等
- 备份：`pg_dump` 定时脚本 + Chroma 数据卷备份，步骤写入 README

## 19. 仓库结构与 Git

```
steel-market/
├── backend/
│   ├── pyproject.toml / alembic/
│   ├── app/                 # FastAPI：api、auth、llm、mcp_client、chat、core、observability
│   ├── steel_core/          # db、ingest、analysis、charts、quote、report、knowledge、versioning
│   ├── mcp_server/          # FastMCP、工具、鉴权中间件、内部管理接口
│   └── tests/
├── frontend/                # Vite + React + TS
├── config/                  # prompts、disclaimers、默认阈值、点位种子
├── data/                    # inbox、templates、exports（仅 templates 入库）
├── knowledge/               # 公共知识文档
├── docs/superpowers/specs/
├── docker-compose.yml / .env.example / README.md / .gitignore
```

- Conventional Commits（`feat(mcp): ...`、`fix(ingest): ...`），一个提交一件事
- `main` + `feature/*`；合并前通过 CI
- SemVer + `CHANGELOG.md`（Keep a Changelog）；自动生成列为迭代
- README：架构图、快速启动、环境变量、每日导入步骤、测试命令、备份说明

## 20. 风险与迭代路线

本节只做范围管理与风险登记，不重复设计细节。设计正文（第 1-19 章）即本期 MVP 的实现依据。

### 20.1 本期 MVP（高优先级项已纳入正文）

| 高优先级能力                     | 设计位置        | 验收要点                            |
| -------------------------- | ----------- | ------------------------------- |
| RAG 过期控制、集合权限、私有库越权防护、引用溯源 | 5.6、7.2、13  | 过期文档默认不返回；跨用户集合访问被拒并记审计；引用带来源脚注 |
| 数据快照与回滚                    | 5.4、11.3    | 覆盖导入生成新版本；回滚恢复上一版本数据与缓存；不物理删除   |
| LLM 独立熔断、熔断告警、鉴权错误码        | 7.4、8.1、8.2 | 单厂商故障不影响其他厂商；状态可查询；登录/令牌错误码可区分  |
| 上传安全校验、角色权限矩阵              | 2、14        | 白名单与魔数校验；权限矩阵逐行测试通过             |
| 监控指标基础方案                   | 15          | `/metrics`、结构化日志、健康检查、系统状态页可用   |
| 数据库最小权限隔离（Agent 读写 / MCP 只读） | 3、7.1、18     | MCP 账号的写操作被数据库拒绝                |

其余 MVP 能力（多用户认证、点位与报价、看板、对话、报价单、日报、知识库、导入）已在正文各章定义。

### 20.2 V2 迭代清单（不进入本期实现）

| 优先级 | 项目                            | 当前预留                        |
| --- | ----------------------------- | --------------------------- |
| 中   | RAG rerank 重排                 | `reranker` 接口存在，MVP 为 no-op |
| 中   | 行情平台 API 自动拉取                 | 导入适配器接口预留，MVP 仅人工 CSV       |
| 中   | 日报定时自动触发                      | 生成逻辑可复用，MVP 手动触发            |
| 中   | 并发压测、混沌测试                     | 指标与健康检查为压测前提                |
| 中   | CHANGELOG 自动生成                | MVP 手工维护，格式已统一              |
| 低   | Chroma 远端化与服务扩容               | MVP 单副本内嵌持久化，迁移路径已隔离        |
| 低   | 增量导入模式                        | MVP 整文件事务 + 版本快照            |
| 二期  | 出口贸易：出口报价、境内外价差、汇率、口岸物流、出口报价单 | 数据模型与工具命名不占用二期语义            |

### 20.3 风险与待确认事项

1. 16 个跟踪点在 Mysteel 对应频道的可获取性，上线前需核对并按可获取规格替换；缺报价的点位返回 warning，不阻塞系统
2. 含税口径：默认按"单价直接计算支售价"，报价单标注待业务确认
3. 免责声明最终文案由业务提供，当前使用配置模板
4. 政策文件摘要的维护人与更新频率未定；过期机制可兜底
5. 部署环境是否具备 Docker（或本地 PostgreSQL/Redis）条件
6. 三家 LLM 的 API Key 与额度；额度不足时依赖熔断降级
7. 私有知识库开放时间；本期仅预留集合与权限结构
8. Mysteel 数据仅限会员授权范围内的自用，禁止程序化抓取；导入合规责任由使用方确认

## 21. 验收标准（MVP）

1. 每日库存 Excel 与 16 点报价 CSV 可导入，重复导入生成新版本，可回滚恢复
2. 看板展示当日报价卡片、库存概览、异常提醒、最新日报
3. 对话可查价、画走势图、算区域/品种价差，数字与数据库一致
4. 异常阈值可在后台修改并立即生效
5. 报价单包含明细、合计、来源、免责声明，可导出 Markdown
6. 日报包含事实稿、图表、来源与免责声明，可存档与查询
7. 知识库检索带引用，过期文档默认不返回
8. 多用户数据隔离通过测试；私有点位无法被他人或 LLM 越权访问
9. 登录、限流、熔断、工具调用上限按规格生效
10. MCP 使用只读数据库账号，写操作被拒绝；REST 报价与对话报价结果一致
11. CI 全部通过，README 可按步骤在干净环境启动
