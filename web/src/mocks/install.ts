import { createMockApi } from "./api";
import type { Scenario } from "./state";

const API_PATHS = /^\/(?:api|v1|agent-api)\//;
const SCENARIOS: readonly string[] = ["default", "empty", "error"];

/**
 * Replaces `fetch` for the API paths with the in-memory mock. Loaded only by mock builds
 * (`vite --mode mock` or `VITE_MOCK_API=1`); a production build does not contain this module.
 *
 * `?mock=empty` or `?mock=error` on the first page load picks a scenario, and `?latency=`
 * sets the delay in milliseconds.
 */
export function installMockApi(): void {
  const query = new URLSearchParams(window.location.search);
  const requested = query.get("mock") ?? "default";
  const scenario = (SCENARIOS.includes(requested) ? requested : "default") as Scenario;
  const latencyMs = Number(query.get("latency") ?? 120);
  const api = createMockApi({ scenario, latencyMs, chunkDelayMs: Math.min(30, latencyMs / 4) });
  const realFetch = window.fetch.bind(window);

  window.fetch = (input, init) => {
    const request = new Request(input, init);
    const url = new URL(request.url);
    return url.origin === window.location.origin && API_PATHS.test(url.pathname) ? api.handle(request) : realFetch(input, init);
  };
}
