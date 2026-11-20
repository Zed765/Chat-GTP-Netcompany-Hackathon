import { agentRoutes } from "./handlers/agent";
import { analystRoutes } from "./handlers/analyst";
import { chatRoutes } from "./handlers/chat";
import { demoRoutes, userFromToken } from "./handlers/demo";
import { inventoryRoutes } from "./handlers/inventory";
import { policyRoutes } from "./handlers/policy";
import { privacyRoutes } from "./handlers/privacy";
import { protectedRoutes } from "./handlers/protected";
import { type Route, problem, sleep } from "./http";
import { type MockState, type Scenario, createState } from "./state";

export interface MockApiOptions {
  scenario?: Scenario;
  /** Delay before each answer, so loading states can be seen. */
  latencyMs?: number;
  /** Delay between streamed chunks. */
  chunkDelayMs?: number;
}

export interface MockApi {
  /** Answers a request the way the gateway and the agent service would. */
  handle: (request: Request) => Promise<Response>;
  state: MockState;
}

/** The whole backend in memory, for development, tests and screenshots. */
export function createMockApi({ scenario = "default", latencyMs = 0, chunkDelayMs = 0 }: MockApiOptions = {}): MockApi {
  const state = createState(scenario);
  const routes: Route[] = [
    ...demoRoutes(state),
    ...chatRoutes(state, chunkDelayMs),
    ...inventoryRoutes(state),
    ...protectedRoutes(state),
    ...policyRoutes(state),
    ...analystRoutes(state),
    ...privacyRoutes(state),
    ...agentRoutes(state, chunkDelayMs),
  ];

  async function handle(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (latencyMs > 0) await sleep(latencyMs);
    for (const candidate of routes) {
      const match = candidate.method === request.method ? candidate.pattern.exec(url.pathname) : null;
      if (!match) continue;
      const user = userFromToken(request.headers.get("Authorization"));
      if (candidate.access !== "public") {
        if (!user) return problem(401, "Sign in first");
        if (candidate.access !== "any" && !candidate.access.includes(user.role)) return problem(403, "This needs a different role");
        if (scenario === "error") return problem(500, "The mock API is set to fail every request (?mock=error).");
      }
      const params = Object.fromEntries(candidate.keys.map((key, index) => [key, decodeURIComponent(match[index + 1] ?? "")]));
      // Public routes never read `user`; every other route has one by this point.
      return candidate.handler({ request, url, params, user: user as NonNullable<typeof user> });
    }
    return problem(404, `The mock API has no route for ${request.method} ${url.pathname}.`);
  }

  return { handle, state };
}
