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
