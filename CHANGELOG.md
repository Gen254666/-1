# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- 项目目录骨架与后端依赖配置
- Pydantic Settings 配置加载与生产密钥校验
- 结构化 JSON 日志、request_id 中间件与敏感字段脱敏
- PostgreSQL 数据模型、Alembic 迁移、双账号（读写/只读）
- 库存 Excel 与 Mysteel 报价 CSV 导入、版本快照与回滚
- 行情查询、历史统计、价差、异动扫描、报价单与日报事实
- Redis 缓存与内存回退、审计日志
- JWT 双令牌认证、刷新轮换、登录锁定、限流、上传安全
- 行情看板、点位、导入、用户与配置 REST 接口
- MCP Server（Streamable HTTP）与 9 个只读工具、服务 JWT
- Chroma 知识库检索、过期过滤、引用与集合权限
- 知识库文档上传（md/txt/pdf/docx）、列表、删除与管理后台页面
- HuggingFace 镜像配置，加速中文嵌入模型下载
- 私有自定义点位与逐日报价录入，按用户隔离版本链
- 强制首次登录修改密码与前端改密页面
- Agent 对话编排（Claude/DeepSeek/豆包）、SSE、熔断与日报生成
- React 前端：登录、看板、对话、报价单、管理后台
- Docker Compose、Nginx 配置与备份脚本
- 部署静态校验脚本与 shell 脚本 LF 行尾规范
- Playwright E2E：登录、看板、智能对话与报价卡片全链路
- 业务数据校验脚本与 16 点位报价模板
- 报价 CSV 命令行导入工具，支持部分点位导入
- 后端 CI（ruff、mypy、pytest）与前端 CI（Vitest、build）
