import { expect, test } from "vitest";

import {
  readLastActivity,
  shouldIdleLogout,
  touchActivity,
} from "../utils/idleTimeout";

test("logs out only after the idle threshold", () => {
  const now = 1_000_000;

  expect(shouldIdleLogout(now - 60_000, now, 1)).toBe(true);
  expect(shouldIdleLogout(now - 59_000, now, 1)).toBe(false);
});

test("ignores invalid timeout values", () => {
  expect(shouldIdleLogout(0, 1_000_000, 0)).toBe(false);
});

test("shares activity timestamp across tabs via storage", () => {
  const storage = new Map<string, string>();
  const adapter = {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => void storage.set(key, value),
    removeItem: (key: string) => void storage.delete(key),
    clear: () => storage.clear(),
    key: () => null,
    length: 0,
  } as unknown as Storage;

  touchActivity(adapter, 1_000);
  expect(readLastActivity(adapter, 2_000)).toBe(1_000);
  expect(readLastActivity(adapter, 70_000)).toBe(1_000);
});
