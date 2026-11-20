import type { Meta, Principal, Session } from "../../api/types";
import { USERS } from "../fixtures/org";
import { EMBEDDER_ID } from "../fixtures/protected";
import { type Route, json, noContent, problem, route } from "../http";
import type { MockState } from "../state";

const TOKEN_PREFIX = "mock-session.";

export function tokenFor(user: Principal): string {
  return TOKEN_PREFIX + user.user_id;
}

export function userFromToken(header: string | null): Principal | null {
  const token = header?.startsWith("Bearer ") ? header.slice(7) : null;
  if (!token?.startsWith(TOKEN_PREFIX)) return null;
  return USERS.find((user) => user.user_id === token.slice(TOKEN_PREFIX.length)) ?? null;
}

export function demoRoutes(state: MockState): Route[] {
  const meta: Meta = {
    product: "A.S.P.I.D.A.",
    seed_demo_data: state.scenario === "default",
    embedder_id: EMBEDDER_ID,
    models: { inline: "gpt-6-luna", offline: "gpt-5-mini", embedding: "text-embedding-3-small" },
    fastapi_version: "0.163.0",
  };
  return [
    route("GET", "/api/meta", "public", () => json(meta)),
    route("GET", "/api/demo/users", "public", () => json(USERS)),
    route("POST", "/api/demo/login", "public", async ({ request }) => {
      const { user_id } = (await request.json()) as { user_id: string };
      const user = USERS.find((candidate) => candidate.user_id === user_id);
      if (!user) return problem(404, "Unknown demo user");
      const session: Session = { token: tokenFor(user), user };
      return json(session);
    }),
    route("GET", "/api/me", "any", ({ user }) => json(user)),
    route("GET", "/api/demo/attacker-inbox", "any", () => json(state.inbox)),
    route("DELETE", "/api/demo/attacker-inbox", "any", () => {
      state.inbox = [];
      return noContent();
    }),
  ];
}
