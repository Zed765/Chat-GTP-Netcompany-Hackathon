/** A failed request, with a message that is safe and useful to show. Status 0 means the server could not be reached. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const FALLBACKS: Record<number, string> = {
  0: "The server cannot be reached. Check that the stack is running, then try again.",
  401: "Your demo session ended and is starting again. Send that once more.",
  403: "Your current role is not allowed to do this.",
  404: "Nothing was found at this address.",
  413: "The file is too large.",
  501: "This part of the gateway is not available in this build yet.",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * Reads FastAPI's `detail` (a string or a list of validation errors), an OpenAI-shaped
 * `error.message`, or the `issues` of a rejected policy document.
 */
export function messageFromBody(body: unknown): string | null {
  if (!isRecord(body)) return typeof body === "string" && body.trim() ? body.trim() : null;
  const { detail, error, issues } = body;
  if (Array.isArray(issues) && issues.length > 0) {
    return issues
      .filter(isRecord)
      .map((issue) => (typeof issue.line === "number" ? `line ${issue.line}: ${String(issue.message)}` : String(issue.message)))
      .join("; ");
  }
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .filter(isRecord)
      .map((item) => {
        const where = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
        return where ? `${where}: ${String(item.msg)}` : String(item.msg);
      });
    return messages.length > 0 ? messages.join("; ") : null;
  }
  if (isRecord(error) && typeof error.message === "string") return error.message;
  return null;
}

export function apiError(status: number, body: unknown): ApiError {
  return new ApiError(status, messageFromBody(body) ?? FALLBACKS[status] ?? `The request failed (HTTP ${status}).`);
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/** Turns anything thrown by a request into an `ApiError`; aborts pass through untouched. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof TypeError) return apiError(0, null);
  return new ApiError(0, error instanceof Error ? error.message : "Something went wrong.");
}
