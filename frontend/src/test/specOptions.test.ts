import { expect, test } from "vitest";

import { buildSpecOptionGroups } from "../utils/specOptions";

test("groups specs and disables incomplete rows", () => {
  const groups = buildSpecOptionGroups([
    {
      block: "方管",
      spec: "100*100*2.5*6m",
      unit_price: 3550,
      weight_per_piece: 24.93,
      tax_add: null,
      pieces: 1,
      total_weight: null,
      price_per_piece: null,
      manufacturer: null,
      row_no: 4,
    },
    {
      block: "方管",
      spec: "100*100*3.0*6m",
      unit_price: 3500,
      weight_per_piece: null,
      tax_add: null,
      pieces: 1,
      total_weight: null,
      price_per_piece: null,
      manufacturer: null,
      row_no: 5,
    },
    {
      block: "矩形管",
      spec: "100*150*2.5*6m",
      unit_price: 3320,
      weight_per_piece: 54.46,
      tax_add: null,
      pieces: 1,
      total_weight: null,
      price_per_piece: null,
      manufacturer: null,
      row_no: 4,
    },
  ]);

  expect(groups.map((group) => group.label)).toEqual(["方管", "矩管"]);
  expect(groups[0].options).toHaveLength(2);
  expect(groups[0].options[0].disabled).toBe(false);
  expect(groups[0].options[1].disabled).toBe(true);
  expect(groups[0].options[1].label).toContain("库存数据不全");
});
