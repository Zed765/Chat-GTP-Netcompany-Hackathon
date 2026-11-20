import createClient, { type Client, type Middleware } from "openapi-fetch";
import { sessionStore } from "../auth/session";
import type { paths as AgentPaths } from "./agent";
import { apiError, isAbort, toApiError } from "./errors";
import type { paths as GatewayPaths } from "./gateway";

export interface TokenSource {
  token(): string | null;
  refresh(): Promise<string | null>;
}

export interface ClientOptions {
  baseUrl?: string;
  fetch?: (request: Request) => Promise<Response>;
  tokens?: TokenSource;
}

const storedTokens: TokenSource = {
  token: () => sessionStore.get()?.token ?? null,
  refresh: () => sessionStore.refresh(),
};

/** Sends the bearer token, and after a 401 signs in again once and replays the request. */
function bearerAuth(tokens: TokenSource, send: (request: Request) => Promise<Response>): Middleware {
  const replays = new Map<string, Request>();
  return {
    onRequest({ request, id }) {
      const token = tokens.token();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      replays.set(id, request.clone());
      return request;
    },
    async onResponse({ response, id }) {
      const replay = replays.get(id);
      replays.delete(id);
      if (response.status !== 401 || !replay) return undefined;
      const token = await tokens.refresh();
      if (!token) return undefined;
      replay.headers.set("Authorization", `Bearer ${token}`);
      return send(replay);
    },
    onError({ id }) {
      replays.delete(id);
    },
  };
}

function build<Paths extends object>(defaultBase: string, options: ClientOptions): Client<Paths> {
  // Looked up on every call, so a mock build can replace `fetch` after this module has loaded.
  const send = options.fetch ?? ((request: Request) => globalThis.fetch(request));
  const client = createClient<Paths>({ baseUrl: (options.baseUrl ?? "") + defaultBase, fetch: send });
  client.use(bearerAuth(options.tokens ?? storedTokens, send));
  return client;
}

export type GatewayClient = Client<GatewayPaths>;
export type AgentClient = Client<AgentPaths>;

export const createGateway = (options: ClientOptions = {}): GatewayClient => build<GatewayPaths>("", options);
export const createAgent = (options: ClientOptions = {}): AgentClient => build<AgentPaths>("/agent-api", options);

export const gateway = createGateway();
export const agent = createAgent();

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Resolves to the response body, or throws an `ApiError` with a message fit to show. */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await call;
  } catch (error) {
    if (isAbort(error)) throw error;
    throw toApiError(error);
  }
  if (!result.response.ok) throw apiError(result.response.status, result.error);
  return result.data as T;
}

/** A `bodySerializer` for the multipart endpoints: files and plain fields in one form. */
export function asFormData(body: unknown): FormData {
  const form = new FormData();
  for (const [key, value] of Object.entries(body as Record<string, string | Blob | undefined>)) {
    if (value !== undefined) form.append(key, value);
  }
  return form;
}
