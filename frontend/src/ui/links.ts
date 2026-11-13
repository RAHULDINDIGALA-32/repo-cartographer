import type { Citation, DoneEvent, RepoSnapshot } from "@/api/types";

export function repoSnapshot(
  url: string,
  id: number,
  indexedSha?: string | null,
  indexedAt?: string | null,
  defaultBranch?: string | null,
): RepoSnapshot {
  const parts = url.replace(/\/$/, "").split("/");
  return {
    id,
    owner: parts.at(-2) ?? "repository",
    name: parts.at(-1) ?? "codebase",
    url: url.replace(/\/$/, ""),
    defaultBranch: defaultBranch ?? undefined,
    indexedSha: indexedSha ?? null,
    indexedAt: indexedAt ?? null,
  };
}

function validGitHubUrl(value: string | null | undefined, repo: RepoSnapshot) {
  if (!value) return false;
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      url.hostname === "github.com" &&
      url.pathname.toLowerCase().startsWith(`/${repo.owner}/${repo.name}/blob/`)
    );
  } catch {
    return false;
  }
}

function encodedPath(path: string) {
  return path
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
}

export function citationLink(citation: Citation, repo: RepoSnapshot, done?: DoneEvent) {
  if (validGitHubUrl(citation.permalink, repo)) return citation.permalink!;
  const sha = citation.commit_sha ?? done?.staleness?.indexed_sha ?? repo.indexedSha;
  const path = encodedPath(citation.path);
  const anchor =
    citation.start_line === citation.end_line
      ? `#L${citation.start_line}`
      : `#L${citation.start_line}-L${citation.end_line}`;
  return `${repo.url}/blob/${encodeURIComponent(sha ?? repo.defaultBranch ?? "main")}/${path}${anchor}`;
}

export function repoLink(repo: RepoSnapshot) {
  return repo.url;
}
