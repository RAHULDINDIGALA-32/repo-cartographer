import type { BackendState } from "@/api/types";

export function StatusIndicator({ state, elapsed }: { state: BackendState; elapsed: number }) {
  const label =
    state === "ready"
      ? "Server healthy"
      : state === "waking"
        ? `Waking server (${elapsed}s)`
        : state === "degraded"
          ? "Server degraded"
          : "Server unavailable";
  return (
    <span className={`status status-${state}`} title={label}>
      <span className="status-dot" aria-hidden />
      <span className="status-label">{label}</span>
    </span>
  );
}
