export const IDLE_STORAGE_KEY = "steel:last_activity";

export function touchActivity(storage: Storage, nowMs: number = Date.now()): void {
  try {
    storage.setItem(IDLE_STORAGE_KEY, String(nowMs));
  } catch {
    // storage can be unavailable in private browsing; server timeout still applies
  }
}

export function readLastActivity(
  storage: Storage,
  nowMs: number = Date.now(),
): number {
  try {
    const value = Number(storage.getItem(IDLE_STORAGE_KEY));
    return Number.isFinite(value) && value > 0 ? value : nowMs;
  } catch {
    return nowMs;
  }
}

export function shouldIdleLogout(
  lastActivityMs: number,
  nowMs: number,
  minutes: number,
): boolean {
  if (!Number.isFinite(minutes) || minutes <= 0) return false;
  return nowMs - lastActivityMs >= minutes * 60_000;
}

export function idleTimeoutMinutes(): number {
  const configured = Number(import.meta.env.VITE_SESSION_IDLE_MINUTES ?? 60);
  return Number.isFinite(configured) && configured > 0 ? configured : 60;
}
