import type { AskResult, EventOut, ToolOut } from "../../api/types";
import { eventsSince } from "./events";

interface Inputs {
  events: readonly EventOut[];
  tools: readonly ToolOut[];
  now: Date;
}

interface StoredQuestion {
  question: string;
  sql: string;
  answer: (inputs: Inputs) => Pick<AskResult, "answer" | "columns" | "rows" | "chart">;
}

type Row = (string | number)[];

/** Groups events and returns one row per group: the key columns, then the computed ones. */
function group(events: readonly EventOut[], key: (event: EventOut) => string[] | null, measures: ((items: EventOut[]) => number)[]): Row[] {
  const groups = new Map<string, { key: string[]; items: EventOut[] }>();
  for (const event of events) {
    const parts = key(event);
    if (!parts) continue;
    const id = parts.join("\u0000");
    const entry = groups.get(id) ?? { key: parts, items: [] };
    entry.items.push(event);
    groups.set(id, entry);
  }
  return [...groups.values()].map((entry) => [...entry.key, ...measures.map((measure) => measure(entry.items))]);
}

const byNumberDesc = (column: number) => (a: Row, b: Row) => Number(b[column]) - Number(a[column]);
const isShadow = (event: EventOut) => event.tool_status === "unapproved" || event.tool_status === "unknown";
const unmasked = (items: EventOut[]) => items.filter((event) => event.origin === "log").length;

/** The questions answered from stored SQL when no model key is configured. */
export const STORED_QUESTIONS: readonly StoredQuestion[] = [
  {
    question: "Which teams sent client data to unapproved AI tools this week?",
    sql: `SELECT team, tool, count(*) AS prompts,
       count(*) FILTER (WHERE sent_unmasked) AS sent_unmasked
FROM v_events
WHERE ts >= now() - interval '7 days'
  AND channel = 'prompt'
  AND tool_status IN ('unapproved', 'unknown')
  AND data_types && ARRAY['CLIENT']
GROUP BY team, tool
ORDER BY prompts DESC
LIMIT 100`,
    answer: ({ events, tools, now }) => {
      const names = new Map(tools.map((tool) => [tool.slug, tool.name]));
      const rows = group(
        eventsSince(events, now, 7),
        (event) => (event.channel === "prompt" && isShadow(event) && "CLIENT" in event.data_counts ? [event.team, names.get(event.tool ?? "") ?? "Unknown"] : null),
        [(items) => items.length, unmasked],
      ).sort(byNumberDesc(2));
      const teams = new Set(rows.map((row) => row[0]));
      const total = rows.reduce((sum, row) => sum + Number(row[2]), 0);
      return {
        answer: `${teams.size} teams sent ${total} prompts with client data to unapproved AI tools in the last seven days.`,
        columns: ["team", "tool", "prompts", "sent_unmasked"],
        rows,
        chart: { kind: "bar", x: "team", y: ["prompts", "sent_unmasked"] },
      };
    },
  },
  {
    question: "Which unapproved AI tools were used most in the last 14 days?",
    sql: `SELECT t.name AS tool, t.status, count(*) AS prompts
FROM v_events e
JOIN v_tools t ON t.slug = e.tool
WHERE e.ts >= now() - interval '14 days'
  AND e.channel = 'prompt'
  AND t.status IN ('unapproved', 'unknown')
GROUP BY t.name, t.status
ORDER BY prompts DESC
LIMIT 100`,
    answer: ({ events, tools, now }) => {
      const byslug = new Map(tools.map((tool) => [tool.slug, tool]));
      const rows = group(
        eventsSince(events, now, 14),
        (event) => {
          const tool = byslug.get(event.tool ?? "");
          return event.channel === "prompt" && isShadow(event) && tool ? [tool.name, tool.status] : null;
        },
        [(items) => items.length],
      ).sort(byNumberDesc(2));
      return {
        answer: `${rows[0]?.[0] ?? "No tool"} is the most used unapproved AI tool over the last 14 days.`,
        columns: ["tool", "status", "prompts"],
        rows,
        chart: { kind: "bar", x: "tool", y: ["prompts"] },
      };
    },
  },
  {
    question: "How many prompts were blocked or needed a warning each day over the last 14 days?",
    sql: `SELECT date_trunc('day', ts)::date AS day,
       count(*) FILTER (WHERE action = 'block') AS blocked,
       count(*) FILTER (WHERE action = 'warn') AS warned
FROM v_events
WHERE ts >= now() - interval '14 days'
GROUP BY day
ORDER BY day
LIMIT 100`,
    answer: ({ events, now }) => {
      const rows = group(
        eventsSince(events, now, 14),
        (event) => [event.ts.slice(0, 10)],
        [(items) => items.filter((event) => event.action === "block").length, (items) => items.filter((event) => event.action === "warn").length],
      ).sort((a, b) => String(a[0]).localeCompare(String(b[0])));
      const blocked = rows.reduce((sum, row) => sum + Number(row[1]), 0);
      return {
        answer: `${blocked} requests were blocked over the last 14 days.`,
        columns: ["day", "blocked", "warned"],
        rows,
        chart: { kind: "line", x: "day", y: ["blocked", "warned"] },
      };
    },
  },
  {
    question: "Which data types does each team send most often?",
    sql: `SELECT team, data_type, count(*) AS prompts
FROM v_events, unnest(data_types) AS data_type
WHERE ts >= now() - interval '14 days'
GROUP BY team, data_type
ORDER BY prompts DESC
LIMIT 12`,
    answer: ({ events, now }) => {
      const counts = new Map<string, Row>();
      for (const event of eventsSince(events, now, 14)) {
        for (const type of Object.keys(event.data_counts)) {
          const row = counts.get(`${event.team}/${type}`) ?? [event.team, type, 0];
          row[2] = Number(row[2]) + 1;
          counts.set(`${event.team}/${type}`, row);
        }
      }
      const rows = [...counts.values()].sort(byNumberDesc(2)).slice(0, 12);
      return {
        answer: `${rows[0]?.[0] ?? "No team"} sends ${String(rows[0]?.[1] ?? "data").toLowerCase()} data most often.`,
        columns: ["team", "data_type", "prompts"],
        rows,
        chart: null,
      };
    },
  },
  {
    question: "How many prompts with sensitive data did each team send this week, and how many were masked?",
    sql: `SELECT team,
       count(*) AS sensitive_prompts,
       count(*) FILTER (WHERE action = 'redact') AS masked
FROM v_events
WHERE ts >= now() - interval '7 days'
  AND channel = 'prompt'
  AND cardinality(data_types) > 0
GROUP BY team
ORDER BY sensitive_prompts DESC
LIMIT 100`,
    answer: ({ events, now }) => {
      const rows = group(
        eventsSince(events, now, 7),
        (event) => (event.channel === "prompt" && Object.keys(event.data_counts).length > 0 ? [event.team] : null),
        [(items) => items.length, (items) => items.filter((event) => event.action === "redact").length],
      ).sort(byNumberDesc(1));
      return {
        answer: `${rows[0]?.[0] ?? "No team"} sent the most prompts with sensitive data this week.`,
        columns: ["team", "sensitive_prompts", "masked"],
        rows,
        chart: { kind: "bar", x: "team", y: ["sensitive_prompts", "masked"] },
      };
    },
  },
  {
    question: "Which agent tool calls were blocked in the last 14 days, and by which rule?",
    sql: `SELECT agent_tool, rule, count(*) AS calls
FROM v_events
WHERE ts >= now() - interval '14 days'
  AND channel = 'tool_call'
  AND action = 'block'
GROUP BY agent_tool, rule
ORDER BY calls DESC
LIMIT 100`,
    answer: ({ events, now }) => {
      const rows = group(
        eventsSince(events, now, 14),
        (event) => (event.channel === "tool_call" && event.action === "block" ? [event.agent_tool ?? "unknown", event.rule] : null),
        [(items) => items.length],
      ).sort(byNumberDesc(2));
      const total = rows.reduce((sum, row) => sum + Number(row[2]), 0);
      return {
        answer: `${total} agent tool calls were blocked in the last 14 days.`,
        columns: ["agent_tool", "rule", "calls"],
        rows,
        chart: null,
      };
    },
  },
];
