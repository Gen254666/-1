from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable

from steel_core.ingest.inventory import InventoryRow
from steel_core.query.service import normalize_spec

BLOCK_CATEGORY = {"方管": "方管", "矩形管": "矩管"}
CATEGORY_PREFIX = {"方管": "FANG", "矩管": "JU"}
SPEC_CHAR_MAP = {"米": "M", "低": "DI", "Φ": "PHI"}


class PointCodeError(ValueError):
    pass


def category_for_block(block: str) -> str:
    try:
        return BLOCK_CATEGORY[block.strip()]
    except KeyError as exc:
        raise PointCodeError(f"不支持的库存区块: {block}") from exc


def region_for_warehouse(warehouse: str) -> str:
    text = warehouse.strip()
    return "昆明" if "昆明" in text else text


def point_code(category: str, spec: str, region: str) -> str:
    try:
        prefix = CATEGORY_PREFIX[category]
    except KeyError as exc:
        raise PointCodeError(f"不支持的品类: {category}") from exc

    text = unicodedata.normalize("NFKC", spec).strip().upper()
    for source, target in SPEC_CHAR_MAP.items():
        text = text.replace(source, target)
    text = text.replace("×", "*").replace("X", "*")
    text = "".join(text.split())

    chars: list[str] = []
    for char in text:
        if char == "*":
            chars.append("X")
        elif char.isascii():
            chars.append(char if char.isalnum() or char in ".-" else "_")
        else:
            raise PointCodeError(f"规格包含无法编码的字符: {char!r} ({spec})")

    normalized = "".join(chars)
    if not normalized:
        raise PointCodeError(f"规格无法生成编码: {spec}")
    return f"{prefix}_{normalized}_{_region_code(region)}"


def _region_code(region: str) -> str:
    text = unicodedata.normalize("NFKC", region).strip()
    if text == "昆明":
        return "KUNMING"
    ascii_text = "".join(char if char.isascii() and char.isalnum() else "_" for char in text.upper())
    ascii_text = "_".join(part for part in ascii_text.split("_") if part)
    if ascii_text:
        return ascii_text
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:4].upper()
    return f"REGION{digest}"


def canonical_rows(rows: Iterable[InventoryRow]) -> list[InventoryRow]:
    grouped: dict[tuple[str, str], InventoryRow] = {}
    for row in rows:
        key = (row.block, normalize_spec(row.spec))
        current = grouped.get(key)
        if current is None or _pieces(row) > _pieces(current):
            grouped[key] = row
    return list(grouped.values())


def _pieces(row: InventoryRow) -> int:
    return -1 if row.pieces is None else row.pieces
