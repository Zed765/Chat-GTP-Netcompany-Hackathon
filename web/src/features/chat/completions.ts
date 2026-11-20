import type { GatewayClient } from "../../api/client";
import { apiError, isAbort, toApiError } from "../../api/errors";
import { sseData } from "../../api/sse";
import type { ChatCompletionEnvelope, ChatMessage, PolicyErrorResponse, Trace, TraceSummary } from "../../api/types";

export type CompletionEvent =
  | { type: "trace"; trace: Trace }
  | { type: "delta"; text: string }
  | { type: "summary"; summary: TraceSummary };

/** What the gateway did with a prompt: answered it, held it for a decision, or refused it. */
export type CompletionOutcome =
  | { kind: "answer"; events: AsyncGenerator<CompletionEvent> }
  | { kind: "warn"; trace: Trace }
  | { kind: "block"; trace: Trace };

export interface CompletionRequest {
  /** Inventory slug of the AI tool the prompt is for. */
  tool: string;
  /** Scopes the vault, so one entity keeps one placeholder for the whole conversation. */
  conversationId: string;
  messages: ChatMessage[];
  /** The `trace_id` of a warning the user has read and accepted: send the masked version. */
  acknowledge?: string;
  signal?: AbortSignal;
}

function contentOf(choice: Record<string, unknown> | undefined, key: "delta" | "message"): string {
  const part = choice?.[key];
  const content = typeof part === "object" && part !== null ? (part as Record<string, unknown>).content : undefined;
  return typeof content === "string" ? content : "";
}

function* eventsOf(envelope: ChatCompletionEnvelope, key: "delta" | "message"): Generator<CompletionEvent> {
  if (envelope.aspida) yield { type: "trace", trace: envelope.aspida };
  const text = contentOf(envelope.choices[0], key);
  if (text) yield { type: "delta", text };
  if (envelope.aspida_summary) yield { type: "summary", summary: envelope.aspida_summary };
}

/**
 * Reads a streamed completion. The first chunk carries the trace, the chunks after it the
 * restored answer piece by piece, and the last one before `[DONE]` the summary.
 */
export async function* completionEvents(stream: ReadableStream<Uint8Array>): AsyncGenerator<CompletionEvent> {
  for await (const data of sseData(stream)) {
    if (data === "[DONE]") return;
    let envelope: ChatCompletionEnvelope;
    try {
      envelope = JSON.parse(data) as ChatCompletionEnvelope;
    } catch {
      continue;
    }
    yield* eventsOf(envelope, "delta");
  }
}

async function* wholeCompletion(stream: ReadableStream<Uint8Array>): AsyncGenerator<CompletionEvent> {
  yield* eventsOf((await new Response(stream).json()) as ChatCompletionEnvelope, "message");
}

function isPolicyError(body: unknown): body is PolicyErrorResponse {
  return typeof body === "object" && body !== null && "aspida" in body && "error" in body;
}

/** Sends a prompt through the gateway. Block (403) and warn (409) are outcomes, not errors. */
export async function requestCompletion(client: GatewayClient, request: CompletionRequest): Promise<CompletionOutcome> {
  let result: Awaited<ReturnType<typeof post>>;
  try {
    result = await post(client, request);
  } catch (error) {
    if (isAbort(error)) throw error;
    throw toApiError(error);
  }
  const { data, error, response } = result;
  if (response.status === 409 && isPolicyError(error)) return { kind: "warn", trace: error.aspida };
  if (response.status === 403 && isPolicyError(error)) return { kind: "block", trace: error.aspida };
  if (!response.ok || !data) throw apiError(response.status, error);
  const streamed = response.headers.get("Content-Type")?.includes("text/event-stream") ?? false;
  return { kind: "answer", events: streamed ? completionEvents(data) : wholeCompletion(data) };
}

function post(client: GatewayClient, { tool, conversationId, messages, acknowledge, signal }: CompletionRequest) {
  return client.POST("/v1/chat/completions", {
    body: { model: tool, messages, stream: true },
    headers: {
      "X-Aspida-Tool": tool,
      "X-Aspida-Conversation": conversationId,
      ...(acknowledge ? { "X-Aspida-Acknowledge-Warning": acknowledge } : {}),
    },
    parseAs: "stream",
    signal,
  });
}
