import { beforeEach, describe, expect, it } from "vitest";
import { type GatewayClient, createGateway } from "../../api/client";
import { createMockApi } from "../../mocks/api";
import { EXAMPLES } from "../../mocks/fixtures/examples";
import { type Turn, type TurnAction, historyBefore, sendTurn, turnsReducer } from "./turns";

const CHATTERBOX = { slug: "chatterbox-ai", name: "Chatterbox AI" };
const DRAFTPILOT = { slug: "draftpilot", name: "DraftPilot" };
const ATHENA = { slug: "athena-assist", name: "Athena Assist" };

const example = (id: string) => EXAMPLES.find((item) => item.id === id)?.prompt ?? "";

/** A chat session against the in-memory gateway, recording every request it makes. */
function session() {
  const api = createMockApi();
  const requests: Request[] = [];
  const client: GatewayClient = createGateway({
    baseUrl: "http://aspida.test",
    fetch: (request) => {
      requests.push(request.clone());
      return api.handle(request);
    },
    tokens: { token: () => "mock-session.v.tsioutsias", refresh: () => Promise.resolve(null) },
  });
  let turns: Turn[] = [];
  const dispatch = (action: TurnAction) => {
    turns = turnsReducer(turns, action);
  };
  const send = (id: string, tool: Turn["tool"], prompt: string, acknowledge?: string) =>
    sendTurn(client, dispatch, { id, tool, prompt, conversationId: "conversation-1", history: historyBefore(turns, id), acknowledge });
  return { api, requests, dispatch, send, turn: (id: string) => turns.find((turn) => turn.id === id) as Turn, turns: () => turns };
}

let chat: ReturnType<typeof session>;

beforeEach(() => {
  chat = session();
});

describe("a prompt with personal data to an unapproved tool", () => {
  it("is masked on the way out and restored in the answer", async () => {
    await chat.send("t1", CHATTERBOX, example("chat-client-email-en"));
    const turn = chat.turn("t1");

    expect(turn.status).toBe("done");
    expect(turn.trace?.action).toBe("redact");
    expect(turn.trace?.forwarded).toBe(true);

    const sent = turn.trace?.upstream_messages.map((message) => message.content).join("\n") ?? "";
    expect(sent).toContain("<PERSON_1>");
    expect(sent).toContain("<AFM_1>");
    expect(sent).toContain("<IBAN_1>");
    for (const secret of ["Maria Papadopoulou", "094872613", "GR68 9901", "Helios Shipping"]) expect(sent).not.toContain(secret);

    expect(turn.answer).toContain("Maria Papadopoulou");
    expect(turn.answer).toContain("094872613");
    expect(turn.answer).not.toContain("<PERSON_1>");
    expect(turn.summary?.rehydration.unresolved).toEqual([]);
    expect(turn.summary?.rehydration.returned).toBeGreaterThan(0);
  });

  it("works the same in Greek", async () => {
    await chat.send("t1", CHATTERBOX, example("chat-client-email-el"));
    const turn = chat.turn("t1");
    expect(turn.trace?.action).toBe("redact");
    expect(turn.trace?.upstream_messages.at(-1)?.content).not.toContain("Παπαδοπούλου");
    expect(turn.answer).toContain("Μαρία Παπαδοπούλου");
  });

  it("sends the tool, the conversation and the earlier answered turns", async () => {
    await chat.send("t1", CHATTERBOX, "Make this friendlier: our app tracks deliveries.");
    await chat.send("t2", CHATTERBOX, "Shorter, please.");
    const second = chat.requests.at(-1) as Request;
    expect(second.headers.get("X-Aspida-Tool")).toBe("chatterbox-ai");
    expect(second.headers.get("X-Aspida-Conversation")).toBe("conversation-1");
    expect(second.headers.get("Authorization")).toBe("Bearer mock-session.v.tsioutsias");
    expect(second.headers.has("X-Aspida-Acknowledge-Warning")).toBe(false);
    const body = (await second.json()) as { stream: boolean; messages: { role: string }[] };
    expect(body.stream).toBe(true);
    expect(body.messages.map((message) => message.role)).toEqual(["user", "assistant", "user"]);
  });
});

describe("the warn flow", () => {
  it("holds the prompt, then sends the masked version once the warning is acknowledged", async () => {
    await chat.send("t1", DRAFTPILOT, example("chat-financial-warn"));
    const warned = chat.turn("t1");
    expect(warned.status).toBe("warned");
    expect(warned.trace?.action).toBe("warn");
    expect(warned.trace?.needs_acknowledgement).toBe(true);
    expect(warned.trace?.forwarded).toBe(false);
    expect(warned.answer).toBe("");
    // The masked version is already there to show the user what would be sent.
    expect(warned.trace?.upstream_messages.at(-1)?.content).toContain("<PROJECT_1>");

    const warningId = warned.trace?.trace_id;
    await chat.send("t1", DRAFTPILOT, warned.prompt, warningId);
    expect(chat.requests.at(-1)?.headers.get("X-Aspida-Acknowledge-Warning")).toBe(warningId);

    const sent = chat.turn("t1");
    expect(sent.status).toBe("done");
    expect(sent.trace?.forwarded).toBe(true);
    expect(sent.trace?.needs_acknowledgement).toBe(false);
    expect(sent.answer).toContain("Project Atlas");
    expect(chat.turns()).toHaveLength(1);
  });

  it("warns again if the acknowledgement names a different warning", async () => {
    await chat.send("t1", DRAFTPILOT, example("chat-financial-warn"));
    await chat.send("t1", DRAFTPILOT, example("chat-financial-warn"), "not-the-warning");
    expect(chat.turn("t1").status).toBe("warned");
  });

  it("sends nothing when the user cancels, and leaves the turn out of the history", async () => {
    await chat.send("t1", DRAFTPILOT, example("chat-financial-warn"));
    const before = chat.requests.length;
    chat.dispatch({ type: "cancelled", id: "t1" });
    expect(chat.turn("t1").status).toBe("cancelled");
    expect(chat.requests).toHaveLength(before);
    expect(historyBefore(chat.turns(), "next")).toEqual([]);
  });
});

describe("the block flow", () => {
  it("refuses a secret and says why", async () => {
    await chat.send("t1", CHATTERBOX, example("chat-api-key"));
    const turn = chat.turn("t1");
    expect(turn.status).toBe("blocked");
    expect(turn.trace?.rule).toBe("secrets-never-leave");
    expect(turn.trace?.forwarded).toBe(false);
    expect(turn.trace?.upstream_messages).toEqual([]);
    expect(turn.trace?.explanation.summary).toMatch(/secret/i);
    expect(turn.answer).toBe("");
  });

  it("offers an approved alternative, and the same prompt goes through there", async () => {
    await chat.send("t1", CHATTERBOX, example("chat-contract"));
    const blocked = chat.turn("t1");
    expect(blocked.status).toBe("blocked");
    expect(blocked.trace?.explanation.alternatives?.map((tool) => tool.slug)).toEqual(["athena-assist"]);

    await chat.send("t1", ATHENA, blocked.prompt);
    const resent = chat.turn("t1");
    expect(chat.requests.at(-1)?.headers.get("X-Aspida-Tool")).toBe("athena-assist");
    expect(resent.status).toBe("done");
    expect(resent.tool).toEqual(ATHENA);
    expect(resent.trace?.action).toBe("allow");
    expect(chat.turns()).toHaveLength(1);
  });
});

describe("failures", () => {
  it("reports a gateway error on the turn instead of throwing", async () => {
    const failing = createGateway({
      baseUrl: "http://aspida.test",
      fetch: () => Promise.resolve(new Response(JSON.stringify({ detail: "The prompt path is not built yet" }), { status: 501 })),
      tokens: { token: () => "token", refresh: () => Promise.resolve(null) },
    });
    let turns: Turn[] = [];
    await sendTurn(failing, (action) => (turns = turnsReducer(turns, action)), { id: "t1", tool: CHATTERBOX, prompt: "hello", conversationId: "c", history: [] });
    expect(turns[0]?.status).toBe("failed");
    expect(turns[0]?.error).toBe("The prompt path is not built yet");
  });

  it("reports an unreachable server in plain words", async () => {
    const offline = createGateway({ baseUrl: "http://aspida.test", fetch: () => Promise.reject(new TypeError("fetch failed")) });
    let turns: Turn[] = [];
    await sendTurn(offline, (action) => (turns = turnsReducer(turns, action)), { id: "t1", tool: CHATTERBOX, prompt: "hello", conversationId: "c", history: [] });
    expect(turns[0]?.status).toBe("failed");
    expect(turns[0]?.error).toMatch(/cannot be reached/);
  });
});
