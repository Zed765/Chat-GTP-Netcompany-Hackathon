import { sseData } from "../../api/sse";
import type { AgentEvent, AgentMessage, AgentSession, ToolCallEvent, ToolResultEvent, TraceStep } from "../../api/types";

/** The agent conversation as the page shows it: finished messages, the reply in progress, the trace. */
export interface AgentState {
  sessionId: string | null;
  messages: AgentMessage[];
  /** The assistant's reply while it streams; it joins `messages` when the turn ends. */
  reply: string;
  trace: TraceStep[];
  /** The request each tool call belongs to: the index, among the user's messages, of the one it followed. */
  requestOfCall: Record<string, number>;
  tainted: boolean;
  taintSource: string | null;
  /** What the user decided about calls the gateway held for confirmation. */
  decisions: Record<string, "approved" | "rejected">;
  running: boolean;
  error: string | null;
}

export type AgentAction =
  | { type: "loaded"; session: AgentSession }
  | { type: "closed" }
  | { type: "asked"; content: string }
  | { type: "decided"; callId: string; approve: boolean }
  | { type: "event"; event: AgentEvent }
  | { type: "ended" }
  | { type: "failed"; message: string };

export const INITIAL_AGENT_STATE: AgentState = {
  sessionId: null,
  messages: [],
  reply: "",
  trace: [],
  requestOfCall: {},
  tainted: false,
  taintSource: null,
  decisions: {},
  running: false,
  error: null,
};

const requestCount = (state: AgentState) => state.messages.filter((message) => message.role === "user").length;

function withCall(state: AgentState, callId: string): AgentState["requestOfCall"] {
  return callId in state.requestOfCall ? state.requestOfCall : { ...state.requestOfCall, [callId]: requestCount(state) - 1 };
}

function endTurn(state: AgentState): AgentState {
  const messages = state.reply ? [...state.messages, { role: "assistant" as const, content: state.reply }] : state.messages;
  return { ...state, messages, reply: "", running: false };
}

export function agentReducer(state: AgentState, action: AgentAction): AgentState {
  switch (action.type) {
    case "loaded":
      return {
        ...INITIAL_AGENT_STATE,
        sessionId: action.session.session_id,
        messages: action.session.messages,
        trace: action.session.trace,
        requestOfCall: action.session.request_of_call,
        tainted: action.session.tainted,
        taintSource: action.session.taint_source,
      };
    case "closed":
      return INITIAL_AGENT_STATE;
    case "asked":
      return { ...state, messages: [...state.messages, { role: "user", content: action.content }], running: true, error: null };
    case "decided":
      return { ...state, decisions: { ...state.decisions, [action.callId]: action.approve ? "approved" : "rejected" }, running: true, error: null };
    case "event": {
      const { event } = action;
      switch (event.type) {
        case "text":
          return { ...state, reply: state.reply + event.delta };
        case "tool_call": {
          // A call seen before is the same call decided again, after a confirmation.
          const known = state.trace.some((step) => step.type === "tool_call" && step.call_id === event.call_id);
          const trace = known ? state.trace.map((step) => (step.type === "tool_call" && step.call_id === event.call_id ? event : step)) : [...state.trace, event];
          return { ...state, trace, requestOfCall: withCall(state, event.call_id) };
        }
        case "tool_result":
          return { ...state, trace: [...state.trace, event], requestOfCall: withCall(state, event.call_id), tainted: state.tainted || event.tainted };
        case "done":
          return { ...endTurn(state), tainted: event.tainted, taintSource: event.taint_source };
        case "error":
          return { ...endTurn(state), error: event.message };
      }
      return state;
    }
    case "ended":
      return state.running ? endTurn(state) : state;
    case "failed":
      return { ...endTurn(state), error: action.message };
  }
}

/** Each `data:` line of the agent's stream is one event; a line that is not JSON is skipped. */
export async function* agentEvents(stream: ReadableStream<Uint8Array>): AsyncGenerator<AgentEvent> {
  for await (const data of sseData(stream)) {
    try {
      yield JSON.parse(data) as AgentEvent;
    } catch {
      continue;
    }
  }
}

/** One tool call with its result, once it has one. */
export interface Activity {
  callId: string;
  tool: string;
  call: ToolCallEvent | null;
  result: ToolResultEvent | null;
}

/**
 * The tool calls behind each request, in the order they were made, keyed like `requestOfCall`.
 * A session opened again brings that record with it, so every call goes back under its request.
 */
export function activitiesByRequest(state: AgentState): Map<number, Activity[]> {
  const byCall = new Map<string, Activity>();
  for (const step of state.trace) {
    const activity = byCall.get(step.call_id) ?? { callId: step.call_id, tool: step.tool, call: null, result: null };
    byCall.set(step.call_id, step.type === "tool_call" ? { ...activity, call: step } : { ...activity, result: step });
  }
  const last = Math.max(0, requestCount(state) - 1);
  const grouped = new Map<number, Activity[]>();
  for (const activity of byCall.values()) {
    const request = state.requestOfCall[activity.callId] ?? last;
    grouped.set(request, [...(grouped.get(request) ?? []), activity]);
  }
  return grouped;
}

/** A held call waits for the user until they decide; the agent then sends the call again with its outcome. */
export function isAwaitingConfirmation(state: AgentState, step: TraceStep): boolean {
  return step.type === "tool_call" && step.decision.needs_confirmation === true && !(step.call_id in state.decisions) && !state.running;
}
