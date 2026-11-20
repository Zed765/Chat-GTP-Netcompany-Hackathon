import { describe, expect, it } from "vitest";
import { createAgent, createGateway, unwrap } from "../../api/client";
import type { AgentEvent, InjectionProtection, ToolCallEvent, ToolResultEvent } from "../../api/types";
import { createMockApi } from "../../mocks/api";
import { AGENT_PROMPTS } from "../../mocks/fixtures/examples";
import { countPlaceholders } from "../../lib/placeholders";
import { type AgentState, INITIAL_AGENT_STATE, activitiesByRequest, agentEvents, agentReducer, isAwaitingConfirmation } from "./session";

const prompt = (id: keyof typeof AGENT_PROMPTS) => AGENT_PROMPTS[id];

/** Runs one request through the agent the way the page does, at a given protection level. */
async function run(level: InjectionProtection, exampleId: keyof typeof AGENT_PROMPTS) {
  const api = createMockApi();
  const options = (user: string) => ({ baseUrl: "http://aspida.test", fetch: api.handle, tokens: { token: () => `mock-session.${user}`, refresh: () => Promise.resolve(null) } });
  const agent = createAgent(options("v.tsioutsias"));
  await unwrap(createGateway(options("a.bilas")).PUT("/api/policy/injection-protection", { body: { level } }));

  const session = await unwrap(agent.POST("/sessions"));
  let state = agentReducer(INITIAL_AGENT_STATE, { type: "loaded", session });
  const play = async (stream: ReadableStream<Uint8Array> | null | undefined) => {
    if (!stream) throw new Error("no stream");
    for await (const event of agentEvents(stream)) state = agentReducer(state, { type: "event", event });
    state = agentReducer(state, { type: "ended" });
  };

  state = agentReducer(state, { type: "asked", content: prompt(exampleId) });
  const { data } = await agent.POST("/sessions/{session_id}/messages", { params: { path: { session_id: session.session_id } }, body: { content: prompt(exampleId) }, parseAs: "stream" });
  await play(data);

  const confirm = async (callId: string, approve: boolean) => {
    state = agentReducer(state, { type: "decided", callId, approve });
    const answer = await agent.POST("/sessions/{session_id}/confirmations/{call_id}", {
      params: { path: { session_id: session.session_id, call_id: callId } },
      body: { approve },
      parseAs: "stream",
    });
    await play(answer.data);
  };
  return { api, state: () => state, confirm };
}

const calls = (state: AgentState) => state.trace.flatMap((step) => (step.type === "tool_call" ? [step] : []));
const results = (state: AgentState) => state.trace.flatMap((step) => (step.type === "tool_result" ? [step] : []));

describe("scene 3: a web page that hides an instruction", () => {
  it("with protection on, flags the injection, taints the session and blocks the email", async () => {
    const { api, state } = await run("standard", "agent-poisoned-en");
    const page = results(state()).find((step) => step.tool === "web.fetch_page");
    expect(page?.source).toBe("untrusted");
    expect(page?.injection?.flagged).toBe(true);
    expect(page?.preview).toContain(page?.injection?.evidence ?? "missing");
    expect(page?.layers_run).toContain("heuristics");

    const mail = calls(state()).find((step) => step.tool === "mail.send_email");
    expect(mail?.decision.action).toBe("block");
    expect(mail?.decision.rule).toBe("tainted-agent-side-effects");

    expect(state().tainted).toBe(true);
    expect(state().taintSource).toContain("web.fetch_page");
    expect(state().running).toBe(false);
    expect(state().messages.at(-1)?.role).toBe("assistant");
    expect(api.state.inbox).toEqual([]);
  });

  it("with protection off, the email leaves but carries placeholders only", async () => {
    const { api, state } = await run("off", "agent-poisoned-en");
    expect(results(state()).every((step) => !step.injection?.flagged)).toBe(true);
    expect(state().tainted).toBe(false);

    const mail = calls(state()).find((step) => step.tool === "mail.send_email");
    expect(mail?.decision.action).toBe("redact");
    expect(mail?.decision.resolved).toBe(false);

    expect(api.state.inbox).toHaveLength(1);
    const body = api.state.inbox[0]?.body ?? "";
    expect(countPlaceholders(body)).toBeGreaterThan(5);
    for (const real of ["Helios", "Maria", "094872613", "GR68"]) expect(body).not.toContain(real);
  });
});

describe("a call held for confirmation", () => {
  it("waits for the user, then goes ahead when approved", async () => {
    const { state, confirm } = await run("standard", "agent-confirm-en");
    const held = calls(state()).find((step) => step.decision.needs_confirmation);
    expect(held).toBeDefined();
    expect(isAwaitingConfirmation(state(), held as NonNullable<typeof held>)).toBe(true);

    await confirm(held?.call_id ?? "", true);
    expect(state().decisions[held?.call_id ?? ""]).toBe("approved");
    expect(isAwaitingConfirmation(state(), held as NonNullable<typeof held>)).toBe(false);
    expect(results(state()).at(-1)?.tool).toBe("mail.send_email");
    expect(state().messages.at(-1)?.content).toMatch(/sent/);
  });

  it("does not send when rejected", async () => {
    const { state, confirm } = await run("standard", "agent-confirm-en");
    const held = calls(state()).find((step) => step.decision.needs_confirmation);
    await confirm(held?.call_id ?? "", false);
    expect(state().decisions[held?.call_id ?? ""]).toBe("rejected");
    expect(results(state()).some((step) => step.tool === "mail.send_email")).toBe(false);
  });
});

describe("agentReducer", () => {
  const event = (state: AgentState, value: AgentEvent) => agentReducer(state, { type: "event", event: value });

  it("joins streamed text into one assistant message when the turn ends", () => {
    let state = agentReducer(INITIAL_AGENT_STATE, { type: "asked", content: "hello" });
    state = event(state, { type: "text", delta: "Hello, " });
    state = event(state, { type: "text", delta: "Eleni." });
    expect(state.reply).toBe("Hello, Eleni.");
    state = event(state, { type: "done", tainted: false, taint_source: null });
    expect(state.messages).toEqual([
      { role: "user", content: "hello" },
      { role: "assistant", content: "Hello, Eleni." },
    ]);
    expect(state.reply).toBe("");
    expect(state.running).toBe(false);
  });

  it("keeps what arrived when the stream breaks or the agent reports an error", () => {
    let state = agentReducer(INITIAL_AGENT_STATE, { type: "asked", content: "hello" });
    state = event(state, { type: "text", delta: "Partial" });
    state = event(state, { type: "error", message: "The model timed out" });
    expect(state.error).toBe("The model timed out");
    expect(state.messages.at(-1)).toEqual({ role: "assistant", content: "Partial" });
    expect(agentReducer(state, { type: "failed", message: "Connection lost" }).error).toBe("Connection lost");
  });

  it("skips stream lines that are not JSON", async () => {
    const stream = new Response('data: {"type":"text","delta":"a"}\n\ndata: not json\n\ndata: {"type":"done","tainted":false,"taint_source":null}\n\n').body;
    const seen: string[] = [];
    for await (const item of agentEvents(stream as ReadableStream<Uint8Array>)) seen.push(item.type);
    expect(seen).toEqual(["text", "done"]);
  });
});

describe("activitiesByRequest", () => {
  const call = (call_id: string, tool: string): ToolCallEvent => ({
    type: "tool_call",
    call_id,
    tool,
    arguments: {},
    decision: { action: "allow", rule: "default", reason: "", resolved: true, needs_confirmation: false },
    layers_run: [],
  });
  const result = (call_id: string, tool: string): ToolResultEvent => ({ type: "tool_result", call_id, tool, source: "trusted", preview: "", masked_values: 0, injection: null, layers_run: [], tainted: false });
  const after = (state: AgentState, ...events: AgentEvent[]) => events.reduce((current, event) => agentReducer(current, { type: "event", event }), state);

  it("pairs each call with its result and files it under the request it followed", () => {
    let state = agentReducer(INITIAL_AGENT_STATE, { type: "asked", content: "first" });
    state = after(state, call("a", "crm.get_client"), result("a", "crm.get_client"), { type: "text", delta: "Done" }, { type: "done", tainted: false, taint_source: null });
    state = agentReducer(state, { type: "asked", content: "second" });
    state = after(state, call("b", "mail.send_email"));

    const grouped = activitiesByRequest(state);
    expect(grouped.get(0)?.map((activity) => [activity.tool, activity.result !== null])).toEqual([["crm.get_client", true]]);
    expect(grouped.get(1)?.map((activity) => [activity.tool, activity.result !== null])).toEqual([["mail.send_email", false]]);
  });

  it("puts the calls of a session opened again back under their own requests", () => {
    const state = agentReducer(INITIAL_AGENT_STATE, {
      type: "loaded",
      session: {
        session_id: "s-1",
        protection: "standard",
        tainted: false,
        taint_source: null,
        messages: [
          { role: "user", content: "first" },
          { role: "assistant", content: "ok" },
          { role: "user", content: "second" },
          { role: "assistant", content: "sent" },
        ],
        trace: [call("a", "crm.search_clients"), result("a", "crm.search_clients"), call("b", "crm.get_client"), call("c", "mail.send_email")],
        request_of_call: { a: 0, b: 1, c: 1 },
      },
    });

    const grouped = activitiesByRequest(state);
    expect(grouped.get(0)?.map((activity) => activity.tool)).toEqual(["crm.search_clients"]);
    expect(grouped.get(1)?.map((activity) => activity.tool)).toEqual(["crm.get_client", "mail.send_email"]);
  });

  it("puts a call nobody recorded a request for under the last request", () => {
    const state: AgentState = {
      ...INITIAL_AGENT_STATE,
      messages: [
        { role: "user", content: "first" },
        { role: "assistant", content: "ok" },
        { role: "user", content: "second" },
      ],
      trace: [call("a", "crm.get_client"), result("a", "crm.get_client")],
    };
    expect([...activitiesByRequest(state).keys()]).toEqual([1]);
  });
});
