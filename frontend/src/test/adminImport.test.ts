import { expect, test } from "vitest";

import { isAutoQuoteBatch, joinWarnings, rollbackPath } from "../utils/adminImport";

test("detects auto-generated quote batches", () => {
  expect(isAutoQuoteBatch("自动生成-10.25库存状况表.xlsx")).toBe(true);
  expect(isAutoQuoteBatch("10.25库存状况表.xlsx")).toBe(false);
});

test("joins warnings and returns null when empty", () => {
  expect(joinWarnings(["点位减少", "缺少单价"])).toBe("点位减少；缺少单价");
  expect(joinWarnings([])).toBeNull();
  expect(joinWarnings(undefined)).toBeNull();
});

test("builds a confirmed rollback path", () => {
  expect(rollbackPath("abc")).toBe("/api/admin/imports/abc/rollback?confirm=true");
});
