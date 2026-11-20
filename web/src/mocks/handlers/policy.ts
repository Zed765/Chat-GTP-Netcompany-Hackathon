import type { InjectionProtection, PolicyOut, Principal, ReplayResult } from "../../api/types";
import { eventsSince } from "../fixtures/events";
import { type Route, json, problem, route } from "../http";
import { draftRule, readProtectionLevel, validatePolicy, writeProtectionLevel } from "../policy";
import type { MockState } from "../state";

export function activePolicy(state: MockState): PolicyOut {
  return state.policies.find((policy) => policy.active) ?? (state.policies[0] as PolicyOut);
}

function activate(state: MockState, user: Principal, yaml: string, note: string | null): PolicyOut {
  for (const policy of state.policies) policy.active = false;
  const version: PolicyOut = {
    version: Math.max(...state.policies.map((policy) => policy.version)) + 1,
    note,
    author: user.user_id,
    created: new Date().toISOString(),
    active: true,
    yaml,
    injection_protection: readProtectionLevel(yaml),
  };
  state.policies.unshift(version);
  return version;
}

/** A plausible difference, scaled to the recent events. The mock does not evaluate the draft. */
function replay(state: MockState, yaml: string, days: number): ReplayResult {
  const events = eventsSince(state.events, new Date(), days);
  const same = yaml.trim() === activePolicy(state).yaml.trim();
  const share = (fraction: number) => (same ? 0 : Math.round(events.length * fraction));
  const transitions = [
    { from_action: "redact", to_action: "block", count: share(0.031) },
    { from_action: "warn", to_action: "block", count: share(0.014) },
    { from_action: "allow", to_action: "warn", count: share(0.011) },
  ] as const;
  const changed = transitions.reduce((sum, item) => sum + item.count, 0);
  const breakdown = (keys: readonly (string | null)[], weights: readonly number[]) => {
    const names = [...new Set(keys.filter((key): key is string => key !== null))].slice(0, weights.length);
    return names.map((key, index) => ({
      key,
      total: keys.filter((candidate) => candidate === key).length,
      changed: Math.round(changed * (weights[index] ?? 0)),
    }));
  };
  return {
    days,
    events: events.length,
    changed,
    transitions: transitions.filter((item) => item.count > 0),
    by_team: breakdown(events.map((event) => event.team), [0.34, 0.22, 0.18, 0.12, 0.08, 0.06]).sort((a, b) => b.changed - a.changed),
    by_tool: breakdown(events.map((event) => event.tool), [0.4, 0.27, 0.16, 0.1, 0.07]).sort((a, b) => b.changed - a.changed),
  };
}

export function policyRoutes(state: MockState): Route[] {
  return [
    route("GET", "/api/policy", ["admin"], () => json(activePolicy(state))),
    route("GET", "/api/policy/versions", ["admin"], () => json(state.policies.map(({ yaml: _yaml, injection_protection: _level, ...summary }) => summary))),
    route("GET", "/api/policy/versions/:version", ["admin"], ({ params }) => {
      const policy = state.policies.find((candidate) => candidate.version === Number(params.version));
      return policy ? json(policy) : problem(404, "Unknown policy version");
    }),
    route("POST", "/api/policy/validate", ["admin"], async ({ request }) => {
      const issues = validatePolicy(((await request.json()) as { yaml: string }).yaml);
      return json({ valid: issues.length === 0, issues });
    }),
    route("POST", "/api/policy/draft", ["admin"], async ({ request }) => {
      const { instruction, yaml } = (await request.json()) as { instruction: string; yaml: string };
      return json(draftRule(instruction, yaml));
    }),
    route("POST", "/api/policy/replay", ["admin"], async ({ request }) => {
      const { yaml, days } = (await request.json()) as { yaml: string; days?: number };
      const issues = validatePolicy(yaml);
      return issues.length > 0 ? json({ valid: false, issues }, 400) : json(replay(state, yaml, days ?? 7));
    }),
    route("POST", "/api/policy/activate", ["admin"], async ({ request, user }) => {
      const { yaml, note } = (await request.json()) as { yaml: string; note?: string | null };
      const issues = validatePolicy(yaml);
      if (issues.length > 0) return json({ valid: false, issues }, 400);
      if (yaml === activePolicy(state).yaml) return json(activePolicy(state));
      return json(activate(state, user, yaml, note ?? null));
    }),
    route("GET", "/api/policy/injection-protection", "any", () => json({ level: activePolicy(state).injection_protection })),
    route("PUT", "/api/policy/injection-protection", ["admin"], async ({ request, user }) => {
      const { level } = (await request.json()) as { level: InjectionProtection };
      return json(activate(state, user, writeProtectionLevel(activePolicy(state).yaml, level), `Injection protection set to ${level}`));
    }),
  ];
}
