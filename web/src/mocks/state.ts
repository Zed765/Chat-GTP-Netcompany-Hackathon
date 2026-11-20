import type {
  AgentTrust,
  AgentEvent,
  AgentSession,
  DocumentOut,
  EventOut,
  InboxMessage,
  IngestionOut,
  PatternOut,
  PolicyOut,
  Principal,
  PrivacySettings,
  TermOut,
  ToolOut,
} from "../api/types";
import { buildEvents } from "./fixtures/events";
import { DAY_MS, USERS, isoMinus, mockNow } from "./fixtures/org";
import { buildDocuments, buildPatterns, buildTerms } from "./fixtures/protected";
import { buildTools } from "./fixtures/tools";
import { DEFAULT_POLICY_YAML } from "./policy";

/** `empty` is a clean install with nothing recorded yet; `error` makes every data request fail. */
export type Scenario = "default" | "empty" | "error";

export interface Conversation {
  owner: string;
  /** Entity key to placeholder, and back. */
  placeholders: Map<string, { placeholder: string; dataType: string; value: string }>;
  counters: Map<string, number>;
}

export interface PendingCall {
  callId: string;
  /** The events to play if the user approves, and if they reject. */
  approved: AgentEvent[];
  rejected: AgentEvent[];
}

export interface MockState {
  scenario: Scenario;
  now: Date;
  tools: ToolOut[];
  ingestions: IngestionOut[];
  terms: TermOut[];
  documents: DocumentOut[];
  patterns: PatternOut[];
  policies: PolicyOut[];
  events: EventOut[];
  settings: PrivacySettings;
  inbox: InboxMessage[];
  agentTrust: AgentTrust;
  conversations: Map<string, Conversation>;
  agentSessions: Map<string, AgentSession>;
  pendingCalls: Map<string, PendingCall>;
  /** Trace ids of warnings that are waiting for the user to acknowledge or cancel. */
  warnings: Set<string>;
  /** Which demo user an event belongs to. The gateway derives this from a keyed hash instead. */
  eventOwners: Map<number, string>;
  sequence: number;
}

export function nextId(state: MockState, prefix: string): string {
  state.sequence += 1;
  return `${prefix}-${state.sequence.toString(36).padStart(6, "0")}`;
}

export function createState(scenario: Scenario = "default"): MockState {
  const now = mockNow();
  const empty = scenario !== "default";
  const tools = buildTools(now);
  const events = empty ? [] : buildEvents(now, tools);
  const [, admin] = USERS as [Principal, Principal];
  const base = {
    author: admin.user_id,
    yaml: DEFAULT_POLICY_YAML,
    injection_protection: "standard",
  } as const;

  const state: MockState = {
    scenario,
    now,
    tools: empty ? tools.filter((tool) => tool.is_demo).map((tool) => ({ ...tool, requests_14d: 0, usage_by_team: [] })) : tools,
    ingestions: empty
      ? []
      : [
          {
            id: 2,
            created: isoMinus(now, DAY_MS),
            filename: "dns-2026-11-12.log",
            kind: "dns",
            lines: 9120,
            malformed: 3,
            matched: 801,
            new_tools: 1,
          },
          {
            id: 1,
            created: isoMinus(now, 13 * DAY_MS),
            filename: "access-2026-11-01.log",
            kind: "squid",
            lines: 18240,
            malformed: 0,
            matched: 2317,
            new_tools: 2,
          },
        ],
    terms: buildTerms(now).filter((row) => !empty || row.source === "default"),
    documents: buildDocuments(now).filter((row) => !empty || row.source === "default"),
    patterns: buildPatterns(now).filter((row) => !empty || row.source === "default"),
    policies: empty
      ? [
          {
            ...base,
            version: 1,
            note: "Default policy",
            created: isoMinus(now, 14 * DAY_MS),
            active: true,
          },
        ]
      : [
          {
            ...base,
            version: 3,
            note: "Block contracts to unknown tools",
            created: isoMinus(now, 6 * DAY_MS),
            active: true,
          },
          {
            ...base,
            version: 2,
            note: "Warn on source code to tolerated tools",
            created: isoMinus(now, 12 * DAY_MS),
            active: false,
          },
          {
            ...base,
            version: 1,
            note: "Default policy",
            created: isoMinus(now, 14 * DAY_MS),
            active: false,
          },
        ],
    events,
    settings: {
      retention_days: 90,
      store_snippets: true,
      vault_ttl_hours: 24,
      snippet_chars: 200,
      small_team_threshold: 3,
    },
    inbox: [],
    agentTrust: {
      systems: [
        { server: "crm", trusted: true, tools: ["search_clients", "get_client", "add_note"].map((name) => ({ name, description: null, side_effects: name === "add_note" })) },
        { server: "mail", trusted: false, tools: ["send_email", "list_inbox", "read_email"].map((name) => ({ name, description: null, side_effects: name === "send_email" })) },
        { server: "web", trusted: false, tools: [{ name: "fetch_page", description: null, side_effects: false }] },
      ],
      mail_domains: ["aspida-demo.example"],
    },
    conversations: new Map(),
    agentSessions: new Map(),
    pendingCalls: new Map(),
    warnings: new Set(),
    eventOwners: new Map(events.filter((event, index) => event.team === "Sales" && event.channel === "prompt" && index % 7 === 0).map((event) => [event.id, USERS[0]?.user_id ?? ""])),
    sequence: 0,
  };
  return state;
}
