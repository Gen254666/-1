from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from steel_core.ingest.derived import (
    PointCodeError,
    canonical_rows,
    category_for_block,
    point_code,
    region_for_warehouse,
)
from steel_core.ingest.inventory import parse_inventory_workbook
from steel_core.query.service import normalize_spec


def main() -> int:
    parser = argparse.ArgumentParser(description="校验库存 Excel 与自动行情点位")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--date", dest="effective_date", type=str, default=None)
    args = parser.parse_args()

    explicit_date = date.fromisoformat(args.effective_date) if args.effective_date else None
    try:
        inventory = parse_inventory_workbook(args.inventory, explicit_date=explicit_date)
    except Exception as exc:  # noqa: BLE001
        print(f"库存文件解析失败: {exc}")
        return 1

    canonical = canonical_rows(inventory.rows)
    duplicate_counts = Counter(
        (row.block, normalize_spec(row.spec)) for row in inventory.rows
    )
    duplicates = [
        row.spec
        for row in canonical
        if duplicate_counts[(row.block, normalize_spec(row.spec))] > 1
    ]
    missing_price = [row.spec for row in canonical if row.unit_price is None]
    missing_weight = [row.spec for row in canonical if row.weight_per_piece is None]
    quotable = [
        row
        for row in canonical
        if row.unit_price is not None and row.weight_per_piece is not None
    ]

    code_errors: list[str] = []
    codes: list[str] = []
    region = region_for_warehouse(inventory.warehouse)
    for row in canonical:
        try:
            codes.append(point_code(category_for_block(row.block), row.spec, region))
        except PointCodeError as exc:
            code_errors.append(str(exc))

    print("=== 库存校验 ===")
    print(f"日期: {inventory.effective_date}")
    print(f"仓库: {inventory.warehouse}")
    print(f"行数: {len(inventory.rows)}，唯一规格: {len(canonical)}")
    print(f"区块: {sorted({row.block for row in inventory.rows})}")
    print(f"错误: {len(inventory.errors)}，警告: {len(inventory.warnings)}")
    for issue in inventory.errors[:10]:
        print(f"  [错误] 第{issue.row_no}行 {issue.field}: {issue.message}")
    for issue in inventory.warnings[:10]:
        print(f"  [警告] 第{issue.row_no}行 {issue.field}: {issue.message}")

    print("\n=== 重复规格 ===")
    print(f"重复规格: {len(duplicates)}")
    for spec in duplicates[:10]:
        print(f"  {spec}")

    print("\n=== 自动行情与报价可用性 ===")
    print(f"缺单价规格: {len(missing_price)}")
    for spec in missing_price[:10]:
        print(f"  {spec}")
    print(f"缺支重规格: {len(missing_weight)}")
    for spec in missing_weight[:10]:
        print(f"  {spec}")
    print(f"可报价规格: {len(quotable)}")
    print(f"可生成点位: {len(codes)}，编码错误: {len(code_errors)}")
    for message in code_errors[:10]:
        print(f"  [错误] {message}")
    print(f"编码唯一: {len(set(codes)) == len(codes)}")

    if inventory.errors or code_errors:
        print("\n校验失败")
        return 1

    print("\n校验通过：库存无行级错误，点位编码可生成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
