import type { Principal, Role } from "../api/types";

export interface Context {
  request: Request;
  url: URL;
  params: Record<string, string>;
  /** The signed-in demo user. Routes that need one never run without it. */
  user: Principal;
}

export type Handler = (context: Context) => Response | Promise<Response>;

export interface Route {
  method: string;
  pattern: RegExp;
  keys: string[];
  /** `public` needs no sign-in; otherwise any signed-in role, or only the roles listed. */
  access: "public" | "any" | readonly Role[];
  handler: Handler;
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

/** `/api/tools/:slug` matches one path segment per `:name`. */
export function route(method: Method, path: string, access: Route["access"], handler: Handler): Route {
  const keys: string[] = [];
  const source = path.replace(/:([a-z_]+)/g, (_, key: string) => {
    keys.push(key);
    return "([^/]+)";
  });
  return { method, pattern: new RegExp(`^${source}$`), keys, access, handler };
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function noContent(): Response {
  return new Response(null, { status: 204 });
}

/** An error in FastAPI's shape, which is what the real gateway answers. */
export function problem(status: number, detail: string): Response {
  return json({ detail }, status);
}

export function eventStream(body: ReadableStream<Uint8Array>, headers: Record<string, string> = {}): Response {
  return new Response(body, { headers: { "Content-Type": "text/event-stream", ...headers } });
}

export const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** A stream that emits each chunk after `delayMs`, the way tokens arrive from a model. */
export function chunkedStream(chunks: readonly string[], delayMs: number): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;
  return new ReadableStream({
    async pull(controller) {
      const chunk = chunks[index];
      if (chunk === undefined) {
        controller.close();
        return;
      }
      if (delayMs > 0) await sleep(delayMs);
      controller.enqueue(encoder.encode(chunk));
      index += 1;
    },
  });
}
