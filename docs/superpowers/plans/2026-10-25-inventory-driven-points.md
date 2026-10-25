# 库存规格驱动点位与自动报价 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 10.25 库存表的 370 个方管/矩管规格替换 16 个公共跟踪点，并在每次库存导入时自动生成当日行情，支撑按任意规格快速报价。

**Architecture:** 新增纯规则模块（编码/去重）和数据库推导服务；库存导入事务内 upsert 公共点位、停用旧点位、生成 `MARKET_QUOTE` 版本。查询层过滤 inactive 点位；前端报价页动态加载库存规格，看板按品类筛选；MCP/日报限制输出条数。回滚库存批次时从恢复后的快照重新推导。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy async、PostgreSQL、React 18、TypeScript、Ant Design、Vitest、pytest。

**Spec:** `docs/superpowers/specs/2026-10-25-inventory-driven-points-design.md`

## Global Constraints

- 不新增数据库表结构，不新增 Alembic 迁移。
- 不新增第三方依赖。
- 沿用现有权限矩阵、版本快照、审计日志；所有自动行情来源标记为 `source=inventory`。
- 旧点位只停用（`is_active=false`），不物理删除。
- 10.25 预期：370 个点位、367 条行情、365 个可报价规格。
- Python 行宽 100，提交前通过 `ruff`/测试；前端提交前通过 `npm test` 与 `npm run build`。
- 每个任务独立提交，提交信息使用中文 conventional commit。

## Review Focus

- 库存文件被截断/只剩少量规格时：不得一次性停用大量旧点位；跳过停用并 warning，`--force` 才强制执行。
- 规格缺单价或缺支重时：点位仍创建；缺单价不生成行情；缺支重不可提交报价，前端置灰并提示。
- 同规格多行单价不一致时：取支数最大行，并产生 warning；看板行情与报价取价必须一致。
- 回滚库存后：行情必须与恢复后的库存一致；无恢复快照时当日行情为空；自动行情批次不可单独回滚。
- 新区位首日全部涨跌为空时：日报不得因“按涨跌排序前 30”而空白或报错，应回退为按品类/规格取前 30 并注明首日无涨跌。

---

### Task 1: 纯规则模块（编码、去重）

**Files:**
- Create: `backend/steel_core/ingest/derived.py`
- Test: `backend/tests/unit/test_core/test_derived_points.py`

**Interfaces:**
- Consumes: `steel_core.ingest.inventory.InventoryRow`、`steel_core.query.service.normalize_spec`
- Produces:
  - `class PointCodeError(ValueError)`
  - `def category_for_block(block: str) -> str`
  - `def region_for_warehouse(warehouse: str) -> str`
  - `def point_code(category: str, spec: str, region: str) -> str`
  - `def canonical_rows(rows: Iterable[InventoryRow]) -> list[InventoryRow]`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from decimal import Decimal

import pytest

from steel_core.ingest.derived import (
    PointCodeError,
    canonical_rows,
    category_for_block,
    point_code,
    region_for_warehouse,
)
from steel_core.ingest.inventory import InventoryRow


def _row(block: str, spec: str, price: str | None, pieces: int | None) -> InventoryRow:
    return InventoryRow(
        block=block, spec=spec, unit_price=None if price is None else Decimal(price),
        tax_add=Decimal("220"), weight_per_piece=Decimal("24.93"), pieces=pieces,
        total_weight=None, price_per_piece=None, packaging=None, manufacturer=None, row_no=1,
    )


def test_code_mapping_and_chinese_suffixes() -> None:
    assert category_for_block("方管") == "方管"
    assert category_for_block("矩形管") == "矩管"
    assert region_for_warehouse("昆明宝象库") == "昆明"
    assert point_code("方管", "100*100*2.5*6m", "昆明") == "FANG_100X100X2.5X6M_KUNMING"
    assert point_code("矩管", "100*150*7.75*12m", "昆明") == "JU_100X150X7.75X12M_KUNMING"
    assert point_code("方管", "250*250*12*9.3米", "昆明") == "FANG_250X250X12X9.3M_KUNMING"
    assert point_code("方管", "250*250*11.75*6m低", "昆明") == "FANG_250X250X11.75X6MDI_KUNMING"


def test_unknown_non_ascii_raises() -> None:
    with pytest.raises(PointCodeError):
        point_code("方管", "100*100*2.5*6m★", "昆明")


def test_canonical_rows_keeps_max_pieces() -> None:
    rows = [
        _row("方管", "120*120*3.75*6m", "3320", 2),
        _row("方管", "120*120*3.75*6m", "3320", 268),
        _row("矩形管", "100*150*2.5*6m", "3320", 128),
    ]
    result = canonical_rows(rows)
    assert len(result) == 2
    assert result[0].pieces == 268
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_core/test_derived_points.py -q`
Expected: FAIL with `ModuleNotFoundError: steel_core.ingest.derived`

- [ ] **Step 3: Implement the module**

- `category_for_block`: `{"方管": "方管", "矩形管": "矩管"}`；其他区块抛 `PointCodeError`。
- `region_for_warehouse`: 包含“昆明”返回“昆明”，否则返回 strip 后原文。
- `point_code`：
  - 品类前缀 `方管→FANG`、`矩管→JU`；
  - `spec` 先做 NFKC，再将 `x/×` 转 `X`，去空格，转大写；
  - 非 ASCII 映射 `米→M`、`低→DI`、`Φ→PHI`；
  - 仍含非 ASCII 时抛 `PointCodeError`；
  - 结果 `f"{prefix}_{spec}_{region_code}"`，`region_code` 昆明→`KUNMING`，其他用 ASCII 映射+4 位哈希兜底。
- `canonical_rows`：按 `(block, normalize_spec(spec))` 分组，每组选 `pieces` 最大（None 最小）的行，保持首次出现顺序。

- [ ] **Step 4: Add real-file regression test**

在测试文件追加：若 `10.25库存状况表（部分价格已调）.xlsx` 存在，解析后 `canonical_rows` 得到 370 行，生成编码全为 ASCII、唯一，最长 ≤64。

Run: `cd backend && uv run pytest tests/unit/test_core/test_derived_points.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/steel_core/ingest/derived.py backend/tests/unit/test_core/test_derived_points.py
git commit -m "feat(ingest): 增加库存规格点位编码与去重规则"
```

---

### Task 2: 库存导入自动推导点位与行情

**Files:**
- Create: `backend/steel_core/ingest/derivation.py`
- Modify: `backend/steel_core/ingest/service.py`（`ImportOutcome`、`import_inventory`）
- Modify: `backend/app/api/admin.py`（`_outcome_dict`；`_save_upload` 直接使用原文件名，去掉随机前缀，保证自动批次审计名称正确）
- Test: `backend/tests/integration/test_inventory_derivation.py`

**Interfaces:**
- Consumes: Task 1 的 `canonical_rows`、`point_code`、`category_for_block`、`region_for_warehouse`
- Produces:
  - `@dataclass class DerivationOutcome`，字段：
    `points_created:int=0`、`points_updated:int=0`、`points_deactivated:int=0`、
    `quotes_written:int=0`、`quote_version_id:UUID|None=None`、
    `quote_no_changes:bool=False`、`warnings:list[ParseIssue]=field(default_factory=list)`
  - `async def sync_inventory_derivation(session, *, user_id, effective_date, warehouse, rows, source_file, force=False, deactivate_missing=True) -> DerivationOutcome`
  - `ImportOutcome` 新增字段：`derived_points_created`、`derived_points_updated`、`derived_points_deactivated`、`derived_quotes`、`derived_quote_version_id`、`derived_quote_no_changes`，均有默认值。

- [ ] **Step 1: Write the failing integration tests**

```python
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import DatasetType, PointScope, VersionStatus
from steel_core.db.models.governance import DatasetVersion
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.ingest.service import import_inventory
from tests.unit.test_core.test_inventory_parser import _build_workbook


async def _count(session: AsyncSession, model) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_inventory_import_derives_points_and_quotes(session, tmp_path: Path) -> None:
    user = await _make_user(session)
    path = tmp_path / "10.25库存状况表.xlsx"
    _build_workbook(path, invalid_row=False)

    out = await import_inventory(session, user_id=user.id, path=path, explicit_date=DATE)

    assert out.derived_points_created == 4
    assert out.derived_quotes == 4
    assert await _count(session, PricePoint) == 4
    assert await _count(session, MarketQuote) == 4
    point = await session.scalar(select(PricePoint).where(PricePoint.code == "FANG_100X100X2.5X6M_KUNMING"))
    assert point is not None and point.scope == PointScope.PUBLIC and point.source == "inventory"
    quote = await session.scalar(select(MarketQuote).where(MarketQuote.point_id == point.id))
    assert quote.price == Decimal("3550") and quote.source == "inventory"
    assert quote.change is None


async def test_duplicate_conflicting_price_warns_and_uses_max_pieces(session: AsyncSession) -> None:
    user = await _make_user(session)
    rows = [
        _row("方管", "120*120*3.75*6m", "3320", 2),
        _row("方管", "120*120*3.75*6m", "3300", 268),
    ]
    out = await sync_inventory_derivation(
        session, user_id=user.id, effective_date=DATE, warehouse="昆明宝象库",
        rows=rows, source_file="10.25库存状况表.xlsx",
    )
    await session.commit()
    assert out.points_created == 1
    assert out.quotes_written == 1
    assert any("单价" in warning.message for warning in out.warnings)
    quote = await session.scalar(select(MarketQuote))
    assert quote.price == Decimal("3300")


async def test_reimport_is_idempotent_and_still_derives(session, tmp_path: Path) -> None:
    user = await _make_user(session)
    path = tmp_path / "10.25库存状况表.xlsx"
    _build_workbook(path, invalid_row=False)
    await import_inventory(session, user_id=user.id, path=path, explicit_date=DATE)

    out = await import_inventory(session, user_id=user.id, path=path, explicit_date=DATE)

    assert out.no_changes is True
    assert out.derived_quote_no_changes is True
    versions = await session.scalars(select(DatasetVersion).where(DatasetVersion.dataset_type == DatasetType.MARKET_QUOTE))
    assert len(list(versions)) == 1


async def test_missing_price_creates_point_but_no_quote(session: AsyncSession) -> None:
    user = await _make_user(session)
    rows = [
        _row("方管", "100*100*2.5*6m", "3550", 230),
        _row("方管", "100*100*3.0*6m", None, 100),
        _row("矩形管", "100*150*2.5*6m", "3320", 128),
        _row("矩形管", "100*150*3.0*6m", "3320", 120),
    ]
    out = await sync_inventory_derivation(
        session, user_id=user.id, effective_date=DATE, warehouse="昆明宝象库",
        rows=rows, source_file="10.25库存状况表.xlsx",
    )
    await session.commit()
    assert out.points_created == 4
    assert out.quotes_written == 3
    assert any("单价" in warning.message for warning in out.warnings)


async def test_deactivation_guard_skips_mass_deactivate(session: AsyncSession) -> None:
    user = await _make_user(session)
    for index in range(25):
        session.add(PricePoint(
            scope=PointScope.PUBLIC, code=f"OLD_{index}", category="方管",
            spec=f"{index}*100*2.5*6m", region="昆明", source="inventory",
        ))
    await session.commit()

    out = await sync_inventory_derivation(
        session, user_id=user.id, effective_date=DATE, warehouse="昆明宝象库",
        rows=[_row("方管", "100*100*2.5*6m", "3550", 230)], source_file="10.25库存状况表.xlsx",
    )
    await session.commit()
    assert out.points_deactivated == 0
    assert any("停用" in warning.message for warning in out.warnings)
    assert await _count(session, PricePoint) == 26
```

`_make_user` 使用 `tests.integration.test_ingest_service._make_user` 或本文件内复制最小实现；`_row` 复制 Task 1 测试里的构造器；`DATE = date(2026, 10, 25)`。

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/test_inventory_derivation.py -q`
Expected: FAIL（`derived_points_created` 属性不存在）

- [ ] **Step 3: Implement `sync_inventory_derivation`**

实现顺序：
1. `canonical = canonical_rows(rows)`；为每行计算 code；非 ASCII 编码失败时抛 `PointCodeError`。
2. 查询全部 public 点位；按 code upsert：存在则更新 `category/spec/region/source='inventory'/unit='元/吨'/is_active=True`，不存在则创建。
3. 计算待停用集合：public、active、`source in ('inventory','mysteel')`、code 不在新集合。
4. 防误删：若 `deactivate_missing` 且当前驱动点位数 ≥20 且待停用数 > 当前数×50%，跳过停用并追加 warning；`force=True` 时强制执行。
5. `session.flush()` 后按唯一规格生成行情行：有 `unit_price` 的规格一条，`price=unit_price`、`change=None`、`source='inventory'`、`note='库存表单价'`。
6. `create_import_batch(dataset_type=MARKET_QUOTE, file_name=f"自动生成-{source_file}", file_hash=checksum, rows_total=len(priced), rows_ok=len(priced), rows_failed=0)`；`create_version` 捕获 `NoChangesError` 返回 `quote_no_changes=True`。
7. 无 priced 行时仍创建空版本（用于回滚无快照场景）。
8. 写入 `AuditLog(action="derive.inventory", detail={...})`。
9. 不要在服务内 `commit`，由调用方统一提交。

- [ ] **Step 4: Integrate into `import_inventory`**

- 解析成功后、创建库存版本前，先对 `canonical_rows` 校验编码；失败则 `_record_failed_batch` 并抛 `ImportValidationError`。
- 在 `NoChangesError` 分支：调用 `sync_inventory_derivation(...)` 后再 `commit`，把结果填入 `ImportOutcome`。
- 在成功分支：插入 snapshot/items/audit 后、`commit` 前调用 `sync_inventory_derivation(...)`，合并 warnings。
- `_outcome_dict` 增加上述 derived 字段。
- `_save_upload` 的临时路径改为 `temp_dir / basename`；临时目录本身唯一，不再给文件名加 UUID 前缀，保证 `source_file=path.name` 是原始文件名。

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_inventory_derivation.py tests/integration/test_ingest_service.py tests/integration/test_admin_api.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/steel_core/ingest/derivation.py backend/steel_core/ingest/service.py backend/app/api/admin.py backend/tests/integration/test_inventory_derivation.py
git commit -m "feat(ingest): 库存导入自动创建点位并生成行情"
```

---

### Task 3: 查询过滤 inactive 点位与统一库存取价

**Files:**
- Modify: `backend/steel_core/query/service.py`（`get_quotes`、`get_price_history`、`find_inventory_item`）
- Test: `backend/tests/integration/test_query_service.py`

**Interfaces:**
- Consumes: 现有 `visible_clause`、`normalize_spec`
- Produces: `find_inventory_item(session, *, spec: str, category: str | None = None) -> InventoryRecord | None` 行为变更：多行匹配时取 `pieces` 最大行。

测试辅助：扩展 `tests/integration/test_query_service.py` 的 `_make_point`，支持 `is_active: bool = True` 参数。

- [ ] **Step 1: Write failing tests**

```python
async def test_quotes_and_history_exclude_inactive_points(session) -> None:
    owner = await _make_user(session)
    point = await _make_point(session, "OLD", is_active=False)
    version = await _make_version(session, owner)
    await _add_quote(session, version, point, "3500")

    page = await get_quotes(session, user_id=owner.id)
    assert page.total == 0

    history = await get_price_history(
        session, user_id=owner.id, point_ids=[point.id],
        start_date=QUOTE_DATE - timedelta(days=7), end_date=QUOTE_DATE,
    )
    assert history == []


async def test_find_inventory_item_prefers_max_pieces(session) -> None:
    # 插入同一快照两条 120*120*3.75*6m：pieces=2/price=3300 与 pieces=268/price=3320
    item = await find_inventory_item(session, spec="120×120×3.75×6m")
    assert item.pieces == 268
    assert item.unit_price == Decimal("3320")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/test_query_service.py -k "inactive or max_pieces" -q`
Expected: FAIL（inactive 点位仍返回；取到第一条）

- [ ] **Step 3: Implement**

- `get_quotes` 的 latest-date 查询和 `conditions` 增加 `PricePoint.is_active.is_(True)`。
- `get_price_history` 增加同样过滤。
- `find_inventory_item`：按 `normalize_spec`（可选 category）收集所有匹配行，返回 `pieces` 最大且 `unit_price is not None` 的行。

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_query_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/steel_core/query/service.py backend/tests/integration/test_query_service.py
git commit -m "fix(query): 隐藏停用点位并统一库存取价"
```

---

### Task 4: 回滚重推导与自动行情批次保护

**Files:**
- Create: `backend/steel_core/ingest/derivation.py`（追加 `derive_from_active_snapshot`）
- Modify: `backend/app/api/admin.py:215-243`
- Test: `backend/tests/integration/test_admin_api.py`

**Interfaces:**
- Consumes: Task 2 的 `sync_inventory_derivation`
- Produces: `async def derive_from_active_snapshot(session, *, user_id, effective_date, force=False, allow_empty=False) -> DerivationOutcome | None`
  - 有 active 库存快照：读取 `InventorySnapshot`/`InventoryItem`，调用 `sync_inventory_derivation`
  - 无快照且 `allow_empty=True`：以空 rows、`deactivate_missing=False` 生成空行情版本并 warning
  - 无快照且 `allow_empty=False`：返回 `None`

- [ ] **Step 1: Write failing API tests**

在 `test_admin_api.py` 顶部补充 `import openpyxl`；以下测试放在现有导入测试之后。

```python
async def test_inventory_rollback_rederives_quotes(session, app_client) -> None:
    await _create_user(session, "admin", Role.ADMIN)
    headers = await _login(app_client, "admin")
    first = await _post_inventory(app_client, headers, price=3550)
    second = await _post_inventory(app_client, headers, price=3600)

    quotes = await app_client.get("/api/quotes?page_size=500", headers=headers)
    assert _price(quotes.json(), "FANG_100X100X2.5X6M_KUNMING") == 3600

    rollback = await app_client.post(
        f"/api/admin/imports/{second['batch_id']}/rollback", headers=headers
    )
    assert rollback.status_code == 200
    quotes = await app_client.get("/api/quotes?page_size=500", headers=headers)
    assert _price(quotes.json(), "FANG_100X100X2.5X6M_KUNMING") == 3550


async def test_rollback_first_inventory_clears_quotes(session, app_client) -> None:
    await _create_user(session, "admin", Role.ADMIN)
    headers = await _login(app_client, "admin")
    first = await _post_inventory(app_client, headers, price=3550)
    await app_client.post(f"/api/admin/imports/{first['batch_id']}/rollback", headers=headers)
    quotes = await app_client.get("/api/quotes?page_size=500", headers=headers)
    assert quotes.json()["total"] == 0


async def test_auto_quote_batch_cannot_be_rolled_back(session, app_client) -> None:
    await _create_user(session, "admin", Role.ADMIN)
    headers = await _login(app_client, "admin")
    await _post_inventory(app_client, headers, price=3550)
    imports = (await app_client.get("/api/admin/imports", headers=headers)).json()
    auto = next(row for row in imports if row["file_name"].startswith("自动生成-"))
    response = await app_client.post(f"/api/admin/imports/{auto['id']}/rollback", headers=headers)
    assert response.status_code == 400
    assert response.json()["code"] == "AUTO_BATCH_READONLY"


async def _post_inventory(client, headers, *, price: int) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "10.25库存状况表.xlsx"
        _build_workbook(path, invalid_row=False)
        workbook = openpyxl.load_workbook(path)
        workbook.active["B4"] = price
        workbook.save(path)
        response = await client.post(
            "/api/admin/import/inventory",
            headers=headers,
            files={"file": ("10.25库存状况表.xlsx", path.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"explicit_date": TODAY.isoformat()},
        )
    assert response.status_code == 200, response.text
    return response.json()


def _price(payload: dict, code: str) -> float:
    return next(item["price"] for item in payload["items"] if item["code"] == code)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/test_admin_api.py -k "rederive or clears_quotes or auto_quote" -q`
Expected: FAIL

- [ ] **Step 3: Implement**

- `derive_from_active_snapshot` 查询 active `InventorySnapshot`（join `DatasetVersion.status == ACTIVE`），把 items 转为 `InventoryRow` 后调用同步。
- `admin.py` 回滚端点：
  - 若 `batch.dataset_type == DatasetType.MARKET_QUOTE` 且 `batch.file_name.startswith("自动生成-")`，抛 `ApiError(400, "AUTO_BATCH_READONLY", ...)`。
  - `rollback_version` 后，若批次是 `INVENTORY`，用 `previous.effective_date if previous else batch.effective_date` 调用 `derive_from_active_snapshot(..., allow_empty=True)`。
  - 对 `batch.effective_date` 和重推导日期都调用 `Cache.invalidate_date`。
  - 返回体增加 `derived` 摘要字段。

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_admin_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/steel_core/ingest/derivation.py backend/app/api/admin.py backend/tests/integration/test_admin_api.py
git commit -m "fix(admin): 库存回滚后重推导行情并保护自动批次"
```

---

### Task 5: 种子移除 16 点位与校验脚本改造

**Files:**
- Modify: `backend/steel_core/db/seed.py`（删除 `PUBLIC_POINTS` 与创建循环）
- Modify: `backend/tests/unit/test_core/test_seed_data.py`
- Create: `backend/tests/integration/test_seed_service.py`
- Modify: `scripts/validate_business_data.py`

**Interfaces:**
- Consumes: Task 1 的 `canonical_rows`、`point_code`、`category_for_block`、`region_for_warehouse`
- Produces: `seed_all` 只创建用户/配置；校验脚本参数 `--inventory`（必填）、`--date`（可选）。

- [ ] **Step 1: Write failing tests**

```python
async def test_seed_creates_no_public_points(session) -> None:
    from steel_core.db.seed import seed_all
    result = await seed_all(session, admin_username="admin", admin_password="ChangeMe123!")
    assert result["points"] == 0
    assert await _count(session, PricePoint) == 0
```

`test_seed_data.py` 删除 16 点位相关测试，只保留默认配置测试。

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/test_seed_service.py tests/unit/test_core/test_seed_data.py -q`
Expected: FAIL（当前 seed 创建 16 个点位）

- [ ] **Step 3: Implement seed change**

删除 `PUBLIC_POINTS` 常量与 `existing_codes` 循环；返回值保留 `"points": 0` 兼容旧输出。

- [ ] **Step 4: Rewrite validator**

`scripts/validate_business_data.py`：
- 参数：`--inventory`（必填）、`--date`（可选 ISO 日期）。
- 输出：行数、唯一规格数、区块、错误/警告数、重复规格、缺单价规格、缺支重规格、可报价规格数。
- 用 `canonical_rows` 与 `point_code` 校验全部编码；失败返回 1。
- 不再读取/要求报价 CSV，不导入 `PUBLIC_POINTS`。

- [ ] **Step 5: Verify against real file**

Run:
```bash
cd backend
uv run python ../scripts/validate_business_data.py --inventory "../10.25库存状况表（部分价格已调）.xlsx" --date 2026-10-25
```
Expected: 371 行、370 唯一规格、367 有单价、365 可报价、退出码 0。

- [ ] **Step 6: Run tests and commit**

Run: `cd backend && uv run pytest tests/integration/test_seed_service.py tests/unit/test_core/test_seed_data.py -q`

```bash
git add backend/steel_core/db/seed.py backend/tests/unit/test_core/test_seed_data.py backend/tests/integration/test_seed_service.py scripts/validate_business_data.py
git commit -m "refactor(seed): 移除固定 16 点位并改造业务数据校验"
```

---

### Task 6: 移除公共报价 CSV 导入入口

**Files:**
- Modify: `backend/app/api/admin.py`（删除 `/import/quotes` 路由与 `import_quotes` 导入）
- Modify: `frontend/src/pages/AdminPage.tsx:24-42`（只上传 Excel）
- Delete: `scripts/import_quotes_file.py`
- Delete: `data/templates/mysteel_quotes_16points.csv`
- Test: `backend/tests/integration/test_admin_api.py`

**Interfaces:**
- Consumes: 现有库存导入端点
- Produces: `/api/admin/import/quotes` 不再存在（404）；管理页只接受 `.xlsx`。

- [ ] **Step 1: Write failing test**

```python
async def test_public_quote_csv_endpoint_removed(session, app_client) -> None:
    await _create_user(session, "admin", Role.ADMIN)
    headers = await _login(app_client, "admin")
    response = await app_client.post("/api/admin/import/quotes", headers=headers)
    assert response.status_code in {404, 405}
```

- [ ] **Step 2: Verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_admin_api.py -k quote_csv_endpoint_removed -q`
Expected: FAIL（当前返回 422/400，不是 404/405）

- [ ] **Step 3: Remove backend route and imports**

删除 `import_quotes` 导入、`/import/quotes` 路由；确认 `import_quotes` 核心函数仍被测试使用，保留。

- [ ] **Step 4: Update admin UI**

`ImportsTab`：
- `accept=".xlsx"`；
- `path` 固定 `/api/admin/import/inventory`；
- 按钮文案“上传库存 Excel”；
- 成功消息显示 `新增/更新点位、停用点位、自动生成报价` 数量。

- [ ] **Step 5: Delete obsolete script/template, update README**

README 删除 Mysteel CSV 校验/导入流程，改为“上传库存 Excel → 自动生成点位与行情”。

- [ ] **Step 6: Run tests and frontend build**

Run:
```bash
cd backend && uv run pytest tests/integration/test_admin_api.py -q
cd frontend && npm run build
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/admin.py frontend/src/pages/AdminPage.tsx backend/tests/integration/test_admin_api.py README.md
git rm scripts/import_quotes_file.py data/templates/mysteel_quotes_16points.csv
git commit -m "refactor(import): 移除公共报价 CSV 导入入口"
```

---

### Task 7: 报价页动态规格与看板筛选

**Files:**
- Modify: `backend/steel_core/query/service.py:19`（`MAX_PAGE_SIZE = 500`）
- Modify: `backend/app/api/read.py:209-231`（dashboard 引用 `MAX_PAGE_SIZE`）
- Create: `frontend/src/utils/specOptions.ts`
- Test: `frontend/src/test/specOptions.test.ts`
- Modify: `frontend/src/pages/QuotePage.tsx`
- Modify: `frontend/src/pages/DashboardPage.tsx`
- Modify: `frontend/src/api/types.ts`（如需要）

**Interfaces:**
- Produces:
  - `export interface SpecOption { value: string; label: string; disabled: boolean }`
  - `export interface SpecOptionGroup { label: string; options: SpecOption[] }`
  - `export function buildSpecOptionGroups(items: InventoryItem[]): SpecOptionGroup[]`
  - `GET /api/inventory?page_size=500` 可用；`GET /api/dashboard` 返回全部 367 条行情。

- [ ] **Step 1: Write failing frontend unit test**

```ts
import { describe, expect, test } from "vitest";
import { buildSpecOptionGroups } from "../utils/specOptions";

test("groups specs and disables incomplete rows", () => {
  const groups = buildSpecOptionGroups([
    { block: "方管", spec: "100*100*2.5*6m", unit_price: 3550, weight_per_piece: 24.93, tax_add: null, pieces: 1, total_weight: null, price_per_piece: null, manufacturer: null, row_no: 4 },
    { block: "方管", spec: "100*100*3.0*6m", unit_price: 3500, weight_per_piece: null, tax_add: null, pieces: 1, total_weight: null, price_per_piece: null, manufacturer: null, row_no: 5 },
    { block: "矩形管", spec: "100*150*2.5*6m", unit_price: 3320, weight_per_piece: 54.46, tax_add: null, pieces: 1, total_weight: null, price_per_piece: null, manufacturer: null, row_no: 4 },
  ]);
  expect(groups.map((g) => g.label)).toEqual(["方管", "矩管"]);
  expect(groups[0].options).toHaveLength(2);
  expect(groups[0].options[0].disabled).toBe(false);
  expect(groups[0].options[1].disabled).toBe(true);
  expect(groups[0].options[1].label).toContain("库存数据不全");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- specOptions`
Expected: FAIL（模块不存在）

- [ ] **Step 3: Implement `buildSpecOptionGroups`**

按 `block` 分组（`矩形管` 显示为 `矩管`）；同 block 同 spec 去重（保留第一条）；`disabled = unit_price == null || weight_per_piece == null`；label 为 `` `${spec}` `` 或 `` `${spec}（库存数据不全）` ``。

- [ ] **Step 4: Update QuotePage**

- `useEffect` 调 `apiGet<InventoryPage>("/api/inventory?page_size=500")`；
- `Select` 使用 `options={buildSpecOptionGroups(items)}`、`showSearch`、`optionFilterProp="label"`；
- 保留支数/运费/加工费/含税口径字段；
- 选中 disabled 项不可能提交（AntD 保证），后端仍返回明确 `DATA_UNAVAILABLE`。

- [ ] **Step 5: Update DashboardPage**

- 后端 `dashboard_endpoint` 的 quotes/inventory 使用 `page_size=MAX_PAGE_SIZE`；
- 前端增加 `Tabs`（全部/方管/矩管）与 `Input.Search`；
- 显示 `当前筛选数 / data.quotes.total`；
- `QuoteCards` 接收筛选后的数组；库存表展示全部 371 行，前端分页。

- [ ] **Step 6: Run frontend tests/build and backend tests**

Run:
```bash
cd frontend && npm test && npm run build
cd backend && uv run pytest tests/integration/test_query_service.py tests/integration/test_read_api.py -q
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/steel_core/query/service.py backend/app/api/read.py frontend/src
git commit -m "feat(ui): 报价页加载全部库存规格并支持看板筛选"
```

---

### Task 8: 日报与 MCP 输出限制

**Files:**
- Modify: `backend/steel_core/report/facts.py`
- Modify: `backend/app/report/service.py`
- Modify: `backend/mcp_server/tools.py`
- Modify: `backend/mcp_server/server.py`
- Modify: `backend/tests/integration/test_report_facts.py`
- Modify: `backend/tests/integration/test_mcp_tools.py`
- Test: `backend/tests/unit/test_core/test_report_highlights.py`

**Interfaces:**
- Produces:
  - `def report_quote_highlights(quotes: list[QuoteRecord], limit: int = 30) -> list[QuoteRecord]`
  - `get_meta(session, ctx, *, category=None, query=None, limit=100) -> dict`
  - MCP `get_quotes` 默认 `page_size=50`
  - 日报 payload 增加 `quotes_total`

- [ ] **Step 1: Write failing highlight tests**

```python
def _q(code: str, change: str | None) -> QuoteRecord:
    return QuoteRecord(
        point_id=uuid.uuid4(), code=code, category="方管", spec=f"{code}*6m",
        region="昆明", quote_date=date(2026, 10, 25), price=Decimal("3550"),
        change=None if change is None else Decimal(change), source="inventory",
    )


def test_highlights_prefer_largest_change() -> None:
    quotes = [_q("A", change=None), _q("B", change="10"), _q("C", change="-30"), _q("D", change="5")]
    result = report_quote_highlights(quotes, limit=2)
    assert [q.code for q in result] == ["C", "B"]


def test_highlights_fallback_when_all_changes_null() -> None:
    quotes = [_q("B", change=None), _q("A", change=None)]
    result = report_quote_highlights(quotes, limit=2)
    assert [q.code for q in result] == ["A", "B"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_core/test_report_highlights.py -q`
Expected: FAIL

- [ ] **Step 3: Implement highlights and report payload**

- `report_quote_highlights`：有 change 的按 `abs(change)` 降序取 limit；全部为 null 时按 `(category, spec, code)` 排序取 limit。
- `app/report/service.py`：`facts_payload` 增加 `quotes_total`，`quotes` 使用 highlights；`_facts_markdown` 输出“报价总数 N，展示前 M 条”。
- `SPREAD_PAIRS` 改为 `("FANG_100X100X2.5X6M_KUNMING", "JU_100X150X2.5X6M_KUNMING", "方管-矩管价差")`。

- [ ] **Step 4: Update MCP tools and registration**

- `get_meta` 增加 `query`（对 code/spec 做小写子串匹配）与 `limit`（1..500，默认 100）；payload 增加 `total`，rows 取前 limit。
- `server.py` 的 `get_meta` 增加同名参数并传递。
- `get_quotes` 在 `tools.py` 与 `server.py` 的默认 `page_size` 改为 50。
- `generate_daily_report` 的 payload 使用 highlights 并增加 `quotes_total`；summary 使用总条数。

- [ ] **Step 5: Update existing tests**

- `test_report_facts.py`：创建方管/矩管点位（新编码），断言价差 70；sources 断言改为新编码。
- `test_mcp_tools.py`：`get_meta(..., limit=1)` 断言 `total >= 2` 且 rows 长度为 1；`generate_daily_report` 断言 `quotes_total` 存在。

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_core/test_report_highlights.py tests/integration/test_report_facts.py tests/integration/test_report_service.py tests/integration/test_mcp_tools.py tests/integration/test_chat_api.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/steel_core/report/facts.py backend/app/report/service.py backend/mcp_server/tools.py backend/mcp_server/server.py backend/tests
git commit -m "feat(report): 限制日报与 MCP 输出规模"
```

---

### Task 9: 迁移 CLI、文档与 Docker 验收

**Files:**
- Create: `backend/steel_core/cli/__init__.py`
- Create: `backend/steel_core/cli/sync_inventory.py`
- Create: `scripts/sync_inventory_points.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-10-25-inventory-driven-points-design.md`（状态改为“已确认/已实现”）

**Interfaces:**
- Consumes: Task 2/4 的 `derive_from_active_snapshot`
- Produces: `python -m steel_core.cli.sync_inventory --date 2026-10-25 [--force]`，输出点位数、行情数、警告；无 active 快照时退出码 1。

- [ ] **Step 1: Implement CLI**

`backend/steel_core/cli/sync_inventory.py`：
- argparse：`--date`（必填）、`--force`、`--admin-username`（默认 admin）。
- 创建 async engine；查 admin；调用 `derive_from_active_snapshot`；打印摘要；无快照返回 1。
- `scripts/sync_inventory_points.py` 仅转发到 `main()`。

- [ ] **Step 2: Update docs**

- README：库存上传即自动生成点位/行情；报价页规格来自库存；回滚说明；CLI 命令。
- CHANGELOG：新增本次行为变更。
- 设计文档状态改为“已确认，已实现”。

- [ ] **Step 3: Run full backend/frontend checks**

Run:
```bash
cd backend && uv run ruff check . && uv run pytest -q
cd frontend && npm test && npm run build
cd backend && uv run python ../scripts/validate_deploy.py
```
Expected: 全部 PASS。

- [ ] **Step 4: Rebuild and migrate Docker**

```bash
docker compose build agent mcp-server frontend
docker compose up -d
docker compose exec -T agent alembic upgrade head
docker compose exec -T agent python -m steel_core.cli.sync_inventory --date 2026-10-25
```

Expected 输出：370 点位、367 行情；16 个旧点位停用。

- [ ] **Step 5: Verify data and APIs**

- DB 查询：public active 点位 370；10.25 行情 367；旧 16 点位 inactive。
- 用 minted token 调 `/api/inventory?page_size=500`、`/api/quotes?page_size=500`、`/api/dashboard`，确认 total 与价格。
- 重复执行 CLI，确认行情版本不增加。
- 回滚一次库存批次后确认行情重推导，再重新导入恢复（或在测试库完成，生产库谨慎）。

- [ ] **Step 6: Browser verification**

- 在 Docker 库创建临时验证用户 `e2e_verify`（已知密码、`must_change_password=False`、角色 admin）。
- 用 Playwright 登录 `http://localhost:8080`，检查：看板 367 条、Tab/搜索正常；报价页 370 个规格、365 个可提交，5 个置灰并提示“库存数据不全”。
- 验证后删除临时用户。

- [ ] **Step 7: Commit**

```bash
git add backend/steel_core/cli scripts/sync_inventory_points.py README.md CHANGELOG.md docs/superpowers/specs/2026-10-25-inventory-driven-points-design.md
git commit -m "feat(cli): 增加库存点位同步命令并完成迁移验收"
```

---

## Self-Review Notes

- Spec 覆盖：点位编码/去重（Task 1）、自动行情（Task 2）、inactive 过滤（Task 3）、回滚（Task 4）、seed/校验（Task 5）、CSV 移除（Task 6）、报价页/看板（Task 7）、日报/MCP（Task 8）、迁移与验收（Task 9）。
- 类型一致性：`DerivationOutcome`、`ImportOutcome.*derived_*`、`report_quote_highlights`、`buildSpecOptionGroups` 在任务间名称一致。
- 未触发的不确定项：非昆明仓库与未知非 ASCII 字符按 Task 1 的稳定规则处理；真实数据不触发失败。
