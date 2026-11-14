export function compactNumber(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(
    value,
  );
}
export function integer(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? "—" : new Intl.NumberFormat().format(value);
}
export function duration(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(2)} s`;
}
export function percent(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? "—" : `${Math.round(value * 100)}%`;
}
export function lowSample(count: number | undefined) {
  return (count ?? 0) < 20;
}
export function isGitHubRepoInput(value: string) {
  const candidate = value.trim().replace(/\/$/, "");
  if (/^[^/\s]+\/[^/\s]+$/.test(candidate)) return true;
  try {
    const url = new URL(candidate);
    return (
      url.protocol === "https:" &&
      url.hostname.toLowerCase() === "github.com" &&
      url.pathname.split("/").filter(Boolean).length === 2
    );
  } catch {
    return false;
  }
}
export function savingsSummary(reused: number, embedded: number, estimatedTokensSaved: number) {
  const total = Math.max(0, reused) + Math.max(0, embedded);
  return {
    total,
    reuseRatio: total ? Math.max(0, reused) / total : null,
    tokensSaved: Math.max(0, estimatedTokensSaved),
    noOp: total === 0 && estimatedTokensSaved === 0,
  };
}
export function relative(value?: string | null) {
  if (!value) return "unknown";
  const delta = Date.now() - new Date(value).getTime();
  const minutes = Math.max(0, Math.round(delta / 60_000));
  return minutes < 60
    ? `${minutes}m ago`
    : minutes < 1440
      ? `${Math.round(minutes / 60)}h ago`
      : `${Math.round(minutes / 1440)}d ago`;
}
