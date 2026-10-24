from __future__ import annotations

import argparse
import sys
from pathlib import Path

from steel_core.db.seed import PUBLIC_POINTS
from steel_core.ingest.inventory import parse_inventory_workbook
from steel_core.ingest.quotes import parse_quote_csv
from steel_core.query.service import normalize_spec

PIPE_CATEGORIES = {"方管", "矩管"}


def main() -> int:
    parser = argparse.ArgumentParser(description="校验库存 Excel 与 Mysteel 16 点位报价")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--quotes", type=Path, required=True)
    parser.add_argument("--date", dest="quote_date", type=str, default=None)
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="允许部分点位缺失（只给警告，不判失败）",
    )
    args = parser.parse_args()

    from datetime import date

    explicit_date = date.fromisoformat(args.quote_date) if args.quote_date else None
    expected_codes = {point["code"] for point in PUBLIC_POINTS}
    errors: list[str] = []

    inventory = parse_inventory_workbook(args.inventory, explicit_date=explicit_date)
    quotes = parse_quote_csv(args.quotes, allowed_point_codes=expected_codes)

    print("=== 库存校验 ===")
    print(f"日期: {inventory.effective_date}")
    print(f"行数: {len(inventory.rows)}，区块: {sorted({row.block for row in inventory.rows})}")
    print(f"错误: {len(inventory.errors)}，警告: {len(inventory.warnings)}")
    for issue in inventory.errors[:10]:
        print(f"  [错误] 第{issue.row_no}行 {issue.field}: {issue.message}")
    formula_warnings = [w for w in inventory.warnings if "支售价" in w.message]
    if formula_warnings:
        print(f"  支售价公式偏差: {len(formula_warnings)} 条")
    if inventory.errors:
        errors.append("库存表存在行级错误")

    print("\n=== 16 点位报价校验 ===")
    print(f"有效报价: {len(quotes.rows)}，错误: {len(quotes.errors)}")
    for issue in quotes.errors[:10]:
        print(f"  [错误] 第{issue.row_no}行 {issue.field}: {issue.message}")
    quote_dates = sorted({row.quote_date for row in quotes.rows})
    print(f"报价日期: {quote_dates}")
    if len(quote_dates) > 1:
        errors.append("报价文件包含多个日期")

    present = {row.point_code: row for row in quotes.rows}
    missing = sorted(expected_codes - set(present))
    if missing:
        message = f"缺少 {len(missing)} 个跟踪点位: {missing}"
        if args.allow_missing:
            print(f"警告: {message}")
        else:
            errors.append(message)
            print(f"缺少点位: {missing}")

    inventory_specs = {normalize_spec(row.spec): row for row in inventory.rows}
    print("\n=== 跟踪点与库存匹配 ===")
    for point in PUBLIC_POINTS:
        row = present.get(point["code"])
        price = f"{row.price}" if row else "缺报价"
        if point["category"] in PIPE_CATEGORIES:
            match = inventory_specs.get(normalize_spec(point["spec"]))
            match_text = f"库存匹配(单价 {match.unit_price})" if match else "库存无匹配"
        else:
            match_text = "不适用（库存表未覆盖该品类）"
        print(f"  {point['category']:6} {point['spec']:16} {point['region']} | {price} | {match_text}")

    print("\n=== 待人工确认 ===")
    print("1. 16 个点位在 Mysteel 对应频道是否都有报价（缺报价按实际替换规格/地区）")
    print("2. 支售价口径：当前公式为 单价 × 支重 ÷ 1000；含税加是否计入最终报价需业务确认")
    print("3. 报价单/日报免责文案是否为最终版本")
    print("4. 报价日期与库存日期是否为同一天")

    if errors:
        print("\n校验失败:")
        for error in errors:
            print(f" - {error}")
        return 1
    if missing:
        print(f"\n校验通过（部分数据）：缺少 {len(missing)} 个点位，其余数据可用。")
    else:
        print("\n校验通过：16 个点位齐全，库存文件无行级错误。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
