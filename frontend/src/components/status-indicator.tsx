import type { BackendState } from "@/api/types";

export function StatusIndicator({ state, elapsed }: { state: BackendState; elapsed: number }) {
  const label =
    state === "ready"
      ? "Backend ready"
      : state === "waking"
        ? `Waking backend (${elapsed}s)`
        : state === "degraded"
          ? "Backend degraded"
          : "Backend unavailable";
  return (
    <span className={`status status-${state}`} title={label}>
      <span className="status-dot" aria-hidden />
      <span className="status-label">{label}</span>
    </span>
  );
}
