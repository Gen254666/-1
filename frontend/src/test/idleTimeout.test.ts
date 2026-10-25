import { expect, test } from "vitest";

import { shouldIdleLogout } from "../utils/idleTimeout";

test("logs out only after the idle threshold", () => {
  const now = 1_000_000;

  expect(shouldIdleLogout(now - 60_000, now, 1)).toBe(true);
  expect(shouldIdleLogout(now - 59_000, now, 1)).toBe(false);
});

test("ignores invalid timeout values", () => {
  expect(shouldIdleLogout(0, 1_000_000, 0)).toBe(false);
});
