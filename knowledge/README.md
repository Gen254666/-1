# 知识库内容说明

- 本目录下的 `.md` / `.txt` 会被批量导入公共知识库 `kb_public`。
- `_drafts/` 是待业务确认的模板，默认**不导入**。
- 已整理内容只使用已确认的业务事实；公司全称、联系方式、具体运费/账期/质检条款仍需业务补充。
- 导入命令（Docker）：

```bash
docker compose exec -T agent python -m steel_core.cli.import_knowledge \
  --dir /app/knowledge --doc-type internal_rule --source local
```
