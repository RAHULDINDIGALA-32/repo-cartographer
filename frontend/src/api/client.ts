import { API_BASE_URL } from "./config";
import { parseEvent } from "./schemas";
import { ApiError, type AskEvent, type RepoDetail, type Repository } from "./types";

type RequestOptions = RequestInit & { timeoutMs?: number };

function retryableGet(status: number) {
  return status === 408 || status === 425 || status === 429 || status >= 500;
}

async function parseApiError(response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const error = body && typeof body === "object" && "error" in body ? body.error : null;
  const value = error && typeof error === "object" ? (error as Record<string, unknown>) : {};
  const retryHeader = response.headers.get("Retry-After");
  const retryAfterSeconds = retryHeader ? Number.parseInt(retryHeader, 10) : undefined;
  return new ApiError({
    code: typeof value.code === "string" ? value.code : `http_${response.status}`,
    message:
      typeof value.message === "string" ? value.message : "The request could not be completed.",
    retryable: value.retryable === true || response.status === 429 || response.status >= 500,
    requestId:
      typeof value.request_id === "string"
        ? value.request_id
        : (response.headers.get("X-Request-ID") ?? undefined),
    status: response.status,
    retryAfterSeconds: Number.isFinite(retryAfterSeconds) ? retryAfterSeconds : undefined,
  });
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
  retries = 2,
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 15_000);
  const signal = options.signal;
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
    if (!response.ok) {
      const error = await parseApiError(response);
      if (options.method === undefined || options.method === "GET") {
        if (retries > 0 && retryableGet(response.status)) {
          await new Promise((resolve) => setTimeout(resolve, (3 - retries) * 250));
          return request<T>(path, options, retries - 1);
        }
      }
      throw error;
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal?.aborted) throw new ApiError({ code: "aborted", message: "Request cancelled." });
    if (controller.signal.aborted)
      throw new ApiError({
        code: "network_error",
        message: "The backend is unavailable.",
        retryable: true,
      });
    throw new ApiError({
      code: "network_error",
      message: "The backend is unavailable.",
      retryable: true,
    });
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", onAbort);
  }
}

export const getHealth = (signal?: AbortSignal) => request<{ ok: boolean }>("/health", { signal });
export const getReady = (signal?: AbortSignal) =>
  request<{ ok: boolean; details?: Record<string, unknown> }>("/ready", { signal });
export const listRepos = (signal?: AbortSignal) => request<Repository[]>("/v1/repos", { signal });
export const getRepo = (id: number, signal?: AbortSignal) =>
  request<RepoDetail>(`/v1/repos/${id}`, { signal });
export const postFeedback = (
  payload: { query_log_id: number; rating: -1 | 1; comment?: string },
  signal?: AbortSignal,
) =>
  request<{ ok: boolean }>("/v1/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
  });

export function parseSseFrame(frame: string): { event: string; data: string } | null {
  let event = "message";
  const data: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator < 0 ? line : line.slice(0, separator);
    const value = separator < 0 ? "" : line.slice(separator + 1).replace(/^ /, "");
    if (field === "event") event = value;
    if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

export function splitSseFrames(buffer: string): { frames: string[]; remainder: string } {
  const frames: string[] = [];
  const separator = /\r?\n\r?\n/g;
  let start = 0;
  let match: RegExpExecArray | null;
  while ((match = separator.exec(buffer)) !== null) {
    frames.push(buffer.slice(start, match.index));
    start = separator.lastIndex;
  }
  return { frames, remainder: buffer.slice(start) };
}

export async function* askStream(
  repoId: number,
  question: string,
  options: Record<string, unknown> = {},
  signal?: AbortSignal,
): AsyncGenerator<AskEvent> {
  const controller = new AbortController();
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const response = await fetch(`${API_BASE_URL}/v1/repos/${repoId}/ask`, {
      method: "POST",
      headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
      body: JSON.stringify({ question, stream: true, options }),
      signal: controller.signal,
    });
    if (!response.ok) throw await parseApiError(response);
    if (!response.body)
      throw new ApiError({
        code: "connection_lost",
        message: "Connection lost while answering.",
        retryable: true,
      });
    reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let terminal = false;
    const emit = async function* (frames: string[]): AsyncGenerator<AskEvent> {
      for (const frame of frames) {
        const parsed = parseSseFrame(frame);
        if (!parsed) continue;
        let data: unknown;
        try {
          data = JSON.parse(parsed.data);
        } catch {
          continue;
        }
        const event = parseEvent(parsed.event, data) as AskEvent | null;
        if (!event) continue;
        yield event;
        if (event.kind === "done" || event.kind === "error") terminal = true;
      }
    };
    while (!terminal) {
      let read: ReadableStreamReadResult<Uint8Array>;
      try {
        read = await reader.read();
      } catch (error) {
        if (signal?.aborted) return;
        throw error;
      }
      if (read.done) break;
      buffer += decoder.decode(read.value, { stream: true });
      const split = splitSseFrames(buffer);
      buffer = split.remainder;
      yield* emit(split.frames);
    }
    buffer += decoder.decode();
    if (buffer.trim()) yield* emit(splitSseFrames(`${buffer}\n\n`).frames);
    if (!terminal && !signal?.aborted)
      throw new ApiError({
        code: "connection_lost",
        message: "Connection lost before the answer completed.",
        retryable: true,
      });
  } catch (error) {
    if (signal?.aborted) return;
    if (error instanceof ApiError) throw error;
    throw new ApiError({
      code: "connection_lost",
      message: "Connection lost while answering.",
      retryable: true,
    });
  } finally {
    // A consumer may stop iterating before the server sends a terminal event.
    // Cancel the reader so the fetch body does not remain attached.
    await reader?.cancel().catch(() => undefined);
    signal?.removeEventListener("abort", onAbort);
  }
}
