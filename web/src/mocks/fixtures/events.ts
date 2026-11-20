import type { EventOut, Overview, ToolOut } from "../../api/types";
import { decidePrompt } from "../policy";
import { DAY_MS, TEAMS, type Team, seededRandom, weighted } from "./org";

interface TeamProfile {
  perDay: number;
  tools: readonly (readonly [string, number])[];
  /** Chance that a prompt carries each data type. */
  data: Readonly<Record<string, number>>;
}

const PROFILES: Record<Team, TeamProfile> = {
  Sales: {
    perDay: 26,
    tools: [["athena-assist", 30], ["chatterbox-ai", 22], ["draftpilot", 18], ["lexora-translate", 8], ["meetscribe", 6], ["paraphrase-pro", 5], ["pixelmuse", 3]],
    data: { CLIENT: 0.34, PERSON: 0.3, EMAIL: 0.2, PHONE: 0.12, AFM: 0.06, IBAN: 0.05, CONFIDENTIAL_MARKER: 0.04 },
  },
  Legal: {
    perDay: 15,
    tools: [["athena-assist", 28], ["legalmind", 20], ["lexora-translate", 20], ["chatterbox-ai", 10], ["draftpilot", 6]],
    data: { CONTRACT: 0.3, CLIENT: 0.32, PERSON: 0.22, CONFIDENTIAL_MARKER: 0.16, AFM: 0.05 },
  },
  Finance: {
    perDay: 17,
    tools: [["athena-assist", 25], ["sheetgenius", 30], ["chatterbox-ai", 16], ["summarize-fast", 4], ["legalmind", 3], ["datawhisper", 3]],
    data: { FINANCIAL: 0.34, IBAN: 0.22, AFM: 0.2, CLIENT: 0.2, PERSON: 0.1 },
  },
  Engineering: {
    perDay: 34,
    tools: [["codeharbor", 60], ["athena-assist", 30], ["chatterbox-ai", 8], ["datawhisper", 2]],
    data: { SOURCE_CODE: 0.42, SECRET: 0.04, EMAIL: 0.05, PROJECT: 0.08 },
  },
  HR: {
    perDay: 11,
    tools: [["draftpilot", 25], ["athena-assist", 20], ["chatterbox-ai", 12], ["meetscribe", 10], ["talentscan", 6], ["paraphrase-pro", 5]],
    data: { PERSON: 0.42, HR: 0.3, AMKA: 0.12, HEALTH: 0.06, EMAIL: 0.15 },
  },
  "Customer Support": {
    perDay: 29,
    tools: [["athena-assist", 35], ["draftpilot", 20], ["chatterbox-ai", 20], ["paraphrase-pro", 10], ["lexora-translate", 10]],
    data: { PERSON: 0.4, EMAIL: 0.3, PHONE: 0.22, CLIENT: 0.16, IBAN: 0.04 },
  },
};

const SNIPPETS: Record<string, string> = {
  CLIENT: "Draft a follow-up to <PERSON_1> at <CLIENT_1> about the renewal quote …",
  PERSON: "Rewrite this note to <PERSON_1> so it sounds less formal …",
  IBAN: "Check this payment instruction: transfer to <IBAN_1> for invoice …",
  AFM: "Fill in the supplier form for <CLIENT_1>, tax number <AFM_1> …",
  CONTRACT: "Summarise clause 7 of the agreement with <CLIENT_1> …",
  FINANCIAL: "Turn these Q3 figures into a paragraph for the board …",
  SOURCE_CODE: "Why does this function return None when the list is empty? …",
  HR: "Shorten this performance review for <PERSON_1> …",
};

interface AgentCall {
  tool: string;
  channel: "tool_call" | "tool_result";
  action: EventOut["action"];
  rule: string;
  data: Record<string, number>;
  tainted: boolean;
  flagged: boolean;
  weight: number;
}

const AGENT_CALLS: readonly AgentCall[] = [
  { tool: "crm.search_clients", channel: "tool_result", action: "redact", rule: "agent-model-sees-placeholders", data: { CLIENT: 1, PERSON: 2, EMAIL: 1, PHONE: 1 }, tainted: false, flagged: false, weight: 40 },
  { tool: "mail.send_email", channel: "tool_call", action: "allow", rule: "default", data: { PERSON: 1 }, tainted: false, flagged: false, weight: 22 },
  { tool: "web.fetch_page", channel: "tool_result", action: "allow", rule: "default", data: {}, tainted: true, flagged: false, weight: 14 },
  { tool: "web.fetch_page", channel: "tool_result", action: "allow", rule: "default", data: {}, tainted: true, flagged: true, weight: 4 },
  { tool: "mail.send_email", channel: "tool_call", action: "block", rule: "tainted-agent-side-effects", data: { CLIENT: 3, EMAIL: 3 }, tainted: true, flagged: false, weight: 4 },
  { tool: "mail.send_email", channel: "tool_call", action: "redact", rule: "untrusted-destinations-get-placeholders", data: { CLIENT: 2, IBAN: 1 }, tainted: false, flagged: false, weight: 5 },
];

/** About two weeks of events for the demo organisation, newest first, the same on every load. */
export function buildEvents(now: Date, tools: readonly ToolOut[]): EventOut[] {
  const random = seededRandom(20261114);
  const statusOf = new Map(tools.map((tool) => [tool.slug, tool.status]));
  const events: Omit<EventOut, "id">[] = [];

  for (let day = 13; day >= 0; day -= 1) {
    const dayStart = new Date(now.getTime() - day * DAY_MS);
    const weekend = [0, 6].includes(dayStart.getUTCDay());
    const hoursToday = day === 0 ? Math.max(1, now.getUTCHours()) : 24;
    const stamp = () => new Date(dayStart.getTime() - random() * hoursToday * 3_600_000).toISOString();

    for (const team of TEAMS) {
      const profile = PROFILES[team];
      const count = Math.round(profile.perDay * (weekend ? 0.2 : 0.8 + random() * 0.4));
      for (let index = 0; index < count; index += 1) {
        const tool = weighted(random, profile.tools);
        const status = statusOf.get(tool) ?? "unknown";
        const data: Record<string, number> = {};
        for (const [type, chance] of Object.entries(profile.data)) {
          if (random() < chance) data[type] = 1 + Math.floor(random() * 2.2);
        }
        const { action, rule } = decidePrompt(status, new Set(Object.keys(data)));
        // Shadow use seen only in proxy and activity logs reached the tool as written.
        const observed = status !== "approved" && random() < 0.3;
        const firstType = Object.keys(data)[0];
        events.push({
          ts: stamp(),
          team,
          tool,
          tool_status: status,
          channel: "prompt",
          action,
          rule,
          policy_version: day > 6 ? 2 : 3,
          data_counts: data,
          masked_snippet: firstType && random() < 0.5 ? (SNIPPETS[firstType] ?? null) : null,
          forwarded: observed || action === "allow" || action === "redact",
          sent_unmasked: observed || (action === "allow" && firstType !== undefined),
          origin: observed ? "log" : "gateway",
          agent_tool: null,
          tainted: false,
          injection_flagged: false,
        });
      }
    }

    for (let index = 0; index < (weekend ? 2 : 9); index += 1) {
      const call = weighted(random, AGENT_CALLS.map((item) => [item, item.weight] as const));
      events.push({
        ts: stamp(),
        team: random() < 0.7 ? "Customer Support" : "Sales",
        tool: "company-assistant",
        tool_status: "approved",
        channel: call.channel,
        action: call.action,
        rule: call.rule,
        policy_version: day > 6 ? 2 : 3,
        data_counts: call.data,
        masked_snippet: null,
        forwarded: call.action !== "block",
        sent_unmasked: false,
        origin: "gateway",
        agent_tool: call.tool,
        tainted: call.tainted,
        injection_flagged: call.flagged,
      });
    }
  }

  return events
    .sort((a, b) => a.ts.localeCompare(b.ts))
    .map((event, index) => ({ id: 1000 + index, ...event }))
    .reverse();
}

export function eventsSince(events: readonly EventOut[], now: Date, days: number): EventOut[] {
  const from = new Date(now.getTime() - days * DAY_MS).toISOString();
  return events.filter((event) => event.ts >= from);
}

function countBy<T>(items: readonly T[], keys: (item: T) => readonly string[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of items) for (const key of keys(item)) counts.set(key, (counts.get(key) ?? 0) + 1);
  return counts;
}

const top = (counts: Map<string, number>, limit: number) => [...counts].sort((a, b) => b[1] - a[1]).slice(0, limit);

export function buildOverview(events: readonly EventOut[], tools: readonly ToolOut[], now: Date, days: number): Overview {
  const recent = eventsSince(events, now, days);
  const prompts = recent.filter((event) => event.channel === "prompt");
  const sensitive = recent.filter((event) => Object.keys(event.data_counts).length > 0);
  const types = top(countBy(recent, (event) => Object.keys(event.data_counts)), 8);
  const shadow = new Map(tools.filter((tool) => tool.status === "unapproved" || tool.status === "unknown").map((tool) => [tool.slug, tool]));
  const byTool = top(countBy(prompts, (event) => (event.tool && shadow.has(event.tool) ? [event.tool] : [])), 6);
  const actions = countBy(recent, (event) => [event.action]);
  const byDay = new Map<string, EventOut[]>();
  for (const event of recent) {
    const day = event.ts.slice(0, 10);
    byDay.set(day, [...(byDay.get(day) ?? []), event]);
  }
  const teams = [...TEAMS];
  return {
    days,
    generated: now.toISOString(),
    prompts_inspected: prompts.length,
    sensitive_share: recent.length > 0 ? sensitive.length / recent.length : 0,
    actions: (["allow", "redact", "warn", "block"] as const).map((action) => ({ action, count: actions.get(action) ?? 0 })),
    top_data_types: types.map(([data_type, count]) => ({ data_type, count })),
    top_unapproved_tools: byTool.map(([slug, count]) => {
      const tool = shadow.get(slug) as ToolOut;
      return { tool: slug, name: tool.name, status: tool.status, count };
    }),
    heatmap: {
      teams,
      data_types: types.map(([type]) => type),
      cells: teams.map((team) =>
        types.map(([type]) => recent.filter((event) => event.team === team && type in event.data_counts).length),
      ),
    },
    trend: [...byDay]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([day, items]) => {
        const count = (action: EventOut["action"]) => items.filter((event) => event.action === action).length;
        return {
          day,
          total: items.length,
          sensitive: items.filter((event) => Object.keys(event.data_counts).length > 0).length,
          allow: count("allow"),
          redact: count("redact"),
          warn: count("warn"),
          block: count("block"),
        };
      }),
  };
}
