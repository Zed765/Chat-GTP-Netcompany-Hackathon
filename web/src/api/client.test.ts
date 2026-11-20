import { describe, expect, it } from "vitest";
import { completionEvents } from "../features/chat/completions";
import { createGateway, unwrap } from "./client";
import { ApiError, messageFromBody } from "./errors";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("the gateway client", () => {
  it("signs in again after a 401 and replays the request once", async () => {
    let token = "expired";
    const seen: (string | null)[] = [];
    const client = createGateway({
      baseUrl: "http://aspida.test",
      fetch: (request) => {
        seen.push(request.headers.get("Authorization"));
        return Promise.resolve(request.headers.get("Authorization") === "Bearer fresh" ? json([{ question: "ok" }]) : json({ detail: "Invalid or expired session" }, 401));
      },
      tokens: {
        token: () => token,
        refresh: () => {
          token = "fresh";
          return Promise.resolve(token);
        },
      },
    });
    expect(await unwrap(client.GET("/api/ask/suggestions"))).toEqual([{ question: "ok" }]);
    expect(seen).toEqual(["Bearer expired", "Bearer fresh"]);
  });

  it("gives up with a readable error when signing in again fails", async () => {
    const client = createGateway({
      baseUrl: "http://aspida.test",
      fetch: () => Promise.resolve(json({ detail: "Sign in first" }, 401)),
      tokens: { token: () => null, refresh: () => Promise.resolve(null) },
    });
    await expect(unwrap(client.GET("/api/me"))).rejects.toMatchObject({ status: 401, message: "Sign in first" });
  });

  it("turns a network failure into an ApiError and lets an abort through", async () => {
    const offline = createGateway({ baseUrl: "http://aspida.test", fetch: () => Promise.reject(new TypeError("fetch failed")) });
    await expect(unwrap(offline.GET("/api/meta"))).rejects.toBeInstanceOf(ApiError);

    const aborted = createGateway({ baseUrl: "http://aspida.test", fetch: () => Promise.reject(new DOMException("Aborted", "AbortError")) });
    await expect(unwrap(aborted.GET("/api/meta"))).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("messageFromBody", () => {
  it("reads the shapes the gateway answers with", () => {
    expect(messageFromBody({ detail: "Unknown tool" })).toBe("Unknown tool");
    expect(messageFromBody({ detail: [{ loc: ["body", "reason"], msg: "String should have at least 10 characters" }] })).toBe("reason: String should have at least 10 characters");
    expect(messageFromBody({ error: { message: "Blocked by policy" } })).toBe("Blocked by policy");
    expect(messageFromBody({ valid: false, issues: [{ path: "rules[2].action", message: "Not an action", line: 14 }] })).toBe("line 14: Not an action");
    expect(messageFromBody("")).toBeNull();
    expect(messageFromBody({})).toBeNull();
  });
});

describe("completionEvents", () => {
  const chunk = (fields: object) => `data: ${JSON.stringify({ id: "c", object: "chat.completion.chunk", model: "m", ...fields })}\n\n`;

  it("reads the trace, the answer and the summary, and stops at [DONE]", async () => {
    const body = [
      chunk({ choices: [], aspida: { trace_id: "t1" } }),
      chunk({ choices: [{ index: 0, delta: { role: "assistant" } }] }),
      chunk({ choices: [{ index: 0, delta: { content: "Αγαπητή " } }] }),
      "data: {broken\n\n",
      chunk({ choices: [{ index: 0, delta: { content: "κυρία" } }] }),
      chunk({ choices: [], aspida_summary: { trace_id: "t1" } }),
      "data: [DONE]\n\n",
      chunk({ choices: [{ index: 0, delta: { content: "never read" } }] }),
    ].join("");
    const events = [];
    for await (const event of completionEvents(new Response(body).body as ReadableStream<Uint8Array>)) events.push(event);
    expect(events.map((event) => event.type)).toEqual(["trace", "delta", "delta", "summary"]);
    expect(events.flatMap((event) => (event.type === "delta" ? [event.text] : [])).join("")).toBe("Αγαπητή κυρία");
  });
});
