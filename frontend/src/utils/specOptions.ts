import type { InventoryItem } from "../api/types";

export interface SpecOption {
  value: string;
  label: string;
  disabled: boolean;
}

export interface SpecOptionGroup {
  label: string;
  options: SpecOption[];
}

const BLOCK_LABELS: Record<string, string> = {
  矩形管: "矩管",
};

export function buildSpecOptionGroups(items: InventoryItem[]): SpecOptionGroup[] {
  const groups = new Map<string, SpecOption[]>();
  const seen = new Set<string>();

  for (const item of items) {
    const blockLabel = BLOCK_LABELS[item.block] ?? item.block;
    const key = `${item.block}|${item.spec}`;
    if (seen.has(key)) continue;
    seen.add(key);

    const disabled = item.unit_price == null || item.weight_per_piece == null;
    const option: SpecOption = {
      value: item.spec,
      label: disabled ? `${item.spec}（库存数据不全）` : item.spec,
      disabled,
    };
    const options = groups.get(blockLabel) ?? [];
    options.push(option);
    groups.set(blockLabel, options);
  }

  return Array.from(groups, ([label, options]) => ({ label, options }));
}
