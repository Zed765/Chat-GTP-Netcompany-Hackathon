import type { GatewayClient } from "../../api/client";
import { isAbort, toApiError } from "../../api/errors";
import type { ChatMessage, Trace, TraceSummary } from "../../api/types";
import { requestCompletion } from "./completions";

export type TurnStatus =
  | "sending"
  | "streaming"
  | "done"
  /** The gateway found something and waits: send the masked version, or cancel. */
  | "warned"
  | "blocked"
  | "cancelled"
  | "failed";

/** One prompt and what became of it. */
export interface Turn {
  id: string;
  /** The AI tool the prompt was (last) sent to. */
  tool: { slug: string; name: string };
  prompt: string;
  status: TurnStatus;
  trace: Trace | null;
  summary: TraceSummary | null;
  answer: string;
  error: string | null;
}

export type TurnAction =
  | { type: "sent"; id: string; tool: Turn["tool"]; prompt: string }
  | { type: "trace"; id: string; trace: Trace }
  | { type: "delta"; id: string; text: string }
  | { type: "summary"; id: string; summary: TraceSummary }
  | { type: "finished"; id: string }
  | { type: "warned"; id: string; trace: Trace }
  | { type: "blocked"; id: string; trace: Trace }
  | { type: "cancelled"; id: string }
  | { type: "failed"; id: string; message: string }
  | { type: "cleared" };

function update(turns: Turn[], id: string, change: (turn: Turn) => Turn): Turn[] {
  return turns.map((turn) => (turn.id === id ? change(turn) : turn));
}

export function turnsReducer(turns: Turn[], action: TurnAction): Turn[] {
  switch (action.type) {
    case "sent": {
      const fresh: Turn = { id: action.id, tool: action.tool, prompt: action.prompt, status: "sending", trace: null, summary: null, answer: "", error: null };
      // Sending an existing turn again (after a warning, a block or a failure) restarts it in
      // place; its last trace stays on screen until the new one arrives.
      return turns.some((turn) => turn.id === action.id)
        ? update(turns, action.id, (turn) => ({ ...fresh, trace: turn.trace }))
        : [...turns, fresh];
    }
    case "trace":
      return update(turns, action.id, (turn) => ({ ...turn, trace: action.trace, status: "streaming" }));
    case "delta":
      return update(turns, action.id, (turn) => ({ ...turn, answer: turn.answer + action.text, status: "streaming" }));
    case "summary":
      return update(turns, action.id, (turn) => ({ ...turn, summary: action.summary }));
    case "finished":
      return update(turns, action.id, (turn) => ({ ...turn, status: "done" }));
    case "warned":
      return update(turns, action.id, (turn) => ({ ...turn, trace: action.trace, status: "warned" }));
    case "blocked":
      return update(turns, action.id, (turn) => ({ ...turn, trace: action.trace, status: "blocked" }));
    case "cancelled":
      return update(turns, action.id, (turn) => ({ ...turn, status: "cancelled" }));
    case "failed":
      return update(turns, action.id, (turn) => ({ ...turn, status: "failed", error: action.message }));
    case "cleared":
      return [];
  }
}

/** The conversation so far, as the AI tool should see it: only turns that were answered. */
export function historyBefore(turns: readonly Turn[], id: string): ChatMessage[] {
  const messages: ChatMessage[] = [];
  for (const turn of turns) {
    if (turn.id === id) break;
    if (turn.status !== "done") continue;
    messages.push({ role: "user", content: turn.prompt }, { role: "assistant", content: turn.answer });
  }
  return messages;
}

export interface SendOptions {
  id: string;
  tool: Turn["tool"];
  prompt: string;
  conversationId: string;
  history: ChatMessage[];
  /** Set when the user accepts a warning: the `trace_id` of that warning. */
  acknowledge?: string;
  signal?: AbortSignal;
}

/** Sends one turn and reports everything that happens to it through `dispatch`. */
export async function sendTurn(client: GatewayClient, dispatch: (action: TurnAction) => void, options: SendOptions): Promise<void> {
  const { id, tool, prompt, conversationId, history, acknowledge, signal } = options;
  dispatch({ type: "sent", id, tool, prompt });
  try {
    const outcome = await requestCompletion(client, {
      tool: tool.slug,
      conversationId,
      messages: [...history, { role: "user", content: prompt }],
      acknowledge,
      signal,
    });
    if (outcome.kind === "warn") return dispatch({ type: "warned", id, trace: outcome.trace });
    if (outcome.kind === "block") return dispatch({ type: "blocked", id, trace: outcome.trace });
    for await (const event of outcome.events) dispatch({ ...event, id });
    dispatch({ type: "finished", id });
  } catch (error) {
    if (!isAbort(error)) dispatch({ type: "failed", id, message: toApiError(error).message });
  }
}
