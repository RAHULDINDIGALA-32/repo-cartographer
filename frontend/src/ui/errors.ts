import { ApiError } from "../api/types";

export function userFacingError(error: unknown) {
  if (!(error instanceof ApiError)) return { title: "Connection lost", retryable: true };
  const copy: Record<string, string> = {
    validation_error: "Please check the question and try again.",
    rate_limited: "You have reached the request limit. Please wait before trying again.",
    budget_exhausted: "The daily answer budget has been reached. Please try again later.",
    server_busy: "The service is busy right now. Please try again shortly.",
    repo_not_ready: "This repository is still being indexed.",
    connection_lost: "Connection lost while receiving the answer.",
    network_error: "The backend is unavailable.",
  };
  return {
    title: copy[error.code] ?? "Something went wrong.",
    retryable: error.retryable,
    retryAfterSeconds: error.retryAfterSeconds,
    requestId: error.requestId,
  };
}
