# 钢材行情智能体

面向云贵川钢材贸易的行情分析智能体 MVP：每日导入库存与报价，支持对话查价、价差与异动分析、报价单和日报。

## 当前状态

阶段一：工程奠基。目录、配置、日志与后端 CI 已就绪，数据库接入进行中。

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
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

## 环境变量

```bash
cp .env.example .env
```

按实际环境填写 PostgreSQL 双账号、Redis、JWT 与 LLM Key。生产环境禁止使用默认密钥。

## 设计文档

- 规格：`docs/superpowers/specs/2026-10-23-steel-market-agent-design.md`
- 实现计划：`实现计划.txt`
