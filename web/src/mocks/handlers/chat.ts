import type {
  Action,
  ChatCompletionRequest,
  EventOut,
  Explanation,
  FoundItem,
  PolicyErrorResponse,
  Principal,
  SpanView,
  ToolOut,
  ToolRef,
  Trace,
  TraceSummary,
} from "../../api/types";
import { dataTypeInfo } from "../../lib/dataTypes";
import { countPlaceholders, splitPlaceholders } from "../../lib/placeholders";
import { type Detected, type DetectedCategory, detect, toCodePoints } from "../detect";
import { EXAMPLES } from "../fixtures/examples";
import { type Route, chunkedStream, eventStream, json, noContent, problem, route } from "../http";
import { decidePrompt } from "../policy";
import { type Conversation, type MockState, nextId } from "../state";

const KEEP_PLACEHOLDERS = "Tokens such as <PERSON_1> stand for values that were removed. Keep each one exactly as written.";

export function conversationOf(state: MockState, id: string, owner: string): Conversation {
  const existing = state.conversations.get(id);
  if (existing) return existing;
  const created: Conversation = { owner, placeholders: new Map(), counters: new Map() };
  state.conversations.set(id, created);
  return created;
}

/**
 * Swaps each maskable finding for a placeholder; one entity keeps one placeholder per
 * conversation. A finding that is only flagged stays in the text, with a null placeholder.
 */
export function maskText(text: string, findings: readonly Detected[], conversation: Conversation): { text: string; spans: SpanView[] } {
  let masked = "";
  let cursor = 0;
  const spans: SpanView[] = [];
  for (const finding of findings) {
    const span = {
      start: toCodePoints(text, finding.start),
      end: toCodePoints(text, finding.end),
      data_type: finding.dataType,
      tier: finding.tier,
      recogniser: finding.recogniser,
      encoded: false,
      store: finding.store,
      source: finding.source,
      match_label: finding.matchLabel,
    };
    if (!finding.masked) {
      spans.push({ ...span, placeholder: null });
      continue;
    }
    const key = `${finding.dataType}:${finding.entity}`;
    let entry = conversation.placeholders.get(key);
    if (!entry) {
      const number = (conversation.counters.get(finding.dataType) ?? 0) + 1;
      conversation.counters.set(finding.dataType, number);
      const placeholder = finding.dataType === "SECRET" ? "<SECRET_REDACTED>" : `<${finding.dataType}_${number}>`;
      entry = { placeholder, dataType: finding.dataType, value: finding.text };
      conversation.placeholders.set(key, entry);
    }
    masked += text.slice(cursor, finding.start) + entry.placeholder;
    cursor = finding.end;
    spans.push({ ...span, placeholder: entry.placeholder });
  }
  return { text: masked + text.slice(cursor), spans };
}

/** Puts the real values back. Secrets were never stored, so their placeholder stays. */
export function restoreText(text: string, conversation: Conversation): string {
  const values = new Map([...conversation.placeholders.values()].map((entry) => [entry.placeholder, entry.value]));
  return splitPlaceholders(text)
    .map((part) => (part.kind === "placeholder" && part.dataType !== "SECRET" ? (values.get(part.text) ?? part.text) : part.text))
    .join("");
}

function foundItems(findings: readonly Detected[], categories: readonly DetectedCategory[]): FoundItem[] {
  const items = new Map<string, FoundItem>();
  for (const finding of findings) {
    const item = items.get(finding.dataType);
    if (item) item.count += 1;
    else {
      items.set(finding.dataType, {
        data_type: finding.dataType,
        count: 1,
        tier: finding.tier,
        encoded: false,
        match_label: finding.matchLabel,
        store: finding.store,
        source: finding.source,
      });
    }
  }
  return [
    ...items.values(),
    ...categories.map((category) => ({
      data_type: category.category,
      count: 1,
      tier: category.tier,
      encoded: false,
      match_label: category.matchLabel,
      store: category.store,
      source: category.source,
    })),
  ];
}

function listOf(found: readonly FoundItem[]): string {
  const lowerFirst = (label: string) => label.charAt(0).toLowerCase() + label.slice(1);
  const parts = found.map((item) => `${item.count} × ${lowerFirst(dataTypeInfo(item.data_type).label)}`);
  return parts.length <= 1 ? (parts[0] ?? "") : `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
}

function explain(action: Action, rule: string, tool: ToolOut, found: FoundItem[], alternatives: ToolRef[], acknowledged: boolean): Explanation {
  const status = tool.status === "unknown" ? "a tool we have not reviewed" : `${/^[aeiou]/.test(tool.status) ? "an" : "a"} ${tool.status} tool`;
  const document = found.find((item) => item.store === "fingerprints" && item.source !== "default")?.match_label;
  const summaries: Record<Action, string> = {
    allow:
      found.length === 0
        ? "Nothing sensitive was found, so your text was sent as written."
        : `We found ${listOf(found)}. ${tool.name} is ${status}, so your text was sent as written.`,
    redact: `We found ${listOf(found)}. ${tool.name} is ${status}, so these values were replaced with placeholders before sending and put back in the answer.`,
    warn: acknowledged
      ? `We found ${listOf(found)}. You chose to send the masked version to ${tool.name}.`
      : `We found ${listOf(found)}. ${tool.name} is ${status}: check what would be sent, then send the masked version or cancel.`,
    block:
      rule === "secrets-never-leave"
        ? "Your text contains a secret, such as an API key or a password. Secrets never leave the company, so nothing was sent."
        : `This text ${document ? `matches the protected document "${document}"` : "looks like a contract"}. Contracts may not go to ${status}, so nothing was sent.`,
  };
  const advice: Record<Action, string | null> = {
    allow: null,
    redact: null,
    warn: acknowledged ? null : "If the text is not meant to leave the company, cancel and use an approved tool.",
    block:
      rule === "secrets-never-leave"
        ? "Remove the secret and try again. If it has been shared anywhere else, rotate it."
        : "Use an approved tool for this document.",
  };
  return { summary: summaries[action], found, rule, action, advice: advice[action], alternatives: action === "block" ? alternatives : [] };
}

/** A short draft that reuses the placeholders, the way the stand-in AI tools answer without a model key. */
function draftReply(source: string, masked: string): string {
  const first = (type: string) => splitPlaceholders(masked).find((part) => part.kind === "placeholder" && part.dataType === type)?.text;
  const [person, client, afm, iban, phone, project] = ["PERSON", "CLIENT", "AFM", "IBAN", "PHONE", "PROJECT"].map(first);
  const greek = /\p{Script=Greek}/u.test(source);
  if (person) {
    const details = [afm && (greek ? `ΑΦΜ ${afm}` : `tax number ${afm}`), iban && `IBAN ${iban}`].filter(Boolean).join(greek ? " και " : " and ");
    return greek
      ? [
          `Αγαπητή κυρία ${person},`,
          "",
          `Σας ευχαριστούμε για το μήνυμά σας. Ενημερώσαμε τα στοιχεία${client ? ` της ${client}` : ""}${details ? `: ${details}` : ""}.`,
          phone ? `Αν χρειαστούμε κάτι ακόμη, θα σας καλέσουμε στο ${phone}.` : "Θα επικοινωνήσουμε μαζί σας αν χρειαστούμε κάτι ακόμη.",
          "",
          "Με εκτίμηση,",
          "Ελένη",
        ].join("\n")
      : [
          `Dear ${person},`,
          "",
          `Thank you for your message. We have updated the records${client ? ` for ${client}` : ""}${details ? `: ${details}` : ""}.`,
          phone ? `If we need anything else, we will call you on ${phone}.` : "We will be in touch if we need anything else.",
          "",
          "Kind regards,",
          "Eleni",
        ].join("\n");
  }
  const subject = project ?? client;
  if (subject) {
    return greek
      ? `Σύντομη εκδοχή:\n\n• Τα έσοδα του τριμήνου αυξήθηκαν.\n• Η κερδοφορία μειώθηκε.\n• Κύρια αιτία ήταν το κόστος για το ${subject}.`
      : `Here are the three points:\n\n• Revenue grew quarter on quarter.\n• The margin fell.\n• The main cause was the cost of ${subject}.`;
  }
  return greek
    ? "Ορίστε ένα σύντομο προσχέδιο με βάση το μήνυμά σας. Χωρίς κλειδί μοντέλου, η απάντηση αυτή είναι προκαθορισμένη."
    : "Here is a short draft based on your message. Without a model key this answer is scripted, so it does not depend on what you wrote.";
}

/** Splits text into word-sized pieces, as a model streams it. */
function pieces(text: string): string[] {
  return text.match(/\s*\S+\s*/g) ?? [];
}

function recordEvent(state: MockState, user: Principal, tool: ToolOut, trace: Trace, masked: string): void {
  const counts: Record<string, number> = {};
  for (const item of trace.explanation.found) counts[item.data_type] = item.count;
  const event: EventOut = {
    id: (state.events[0]?.id ?? 999) + 1,
    ts: new Date().toISOString(),
    team: user.team,
    tool: tool.slug,
    tool_status: tool.status,
    channel: "prompt",
    action: trace.action,
    rule: trace.rule,
    policy_version: trace.policy_version,
    data_counts: counts,
    masked_snippet: state.settings.store_snippets && trace.spans.length > 0 ? masked.slice(0, state.settings.snippet_chars) : null,
    forwarded: trace.forwarded,
    sent_unmasked: trace.forwarded && trace.action === "allow" && trace.spans.length > 0,
    origin: "gateway",
    agent_tool: null,
    tainted: false,
    injection_flagged: false,
  };
  state.events.unshift(event);
  state.eventOwners.set(event.id, user.user_id);
}

export function chatRoutes(state: MockState, chunkDelayMs: number): Route[] {
  return [
    route("GET", "/api/examples", "any", ({ url }) => {
      const page = url.searchParams.get("page");
      return json(state.scenario === "empty" ? [] : EXAMPLES.filter((example) => !page || example.page === page));
    }),

    route("POST", "/api/conversations/:conversation_id/end", "any", ({ params }) => {
      state.conversations.delete(params.conversation_id ?? "");
      return noContent();
    }),

    route("POST", "/api/ingest/prompts", ["admin"], async ({ request }) => {
      const records = (await request.json()) as unknown[];
      return json({ ingested: records.length, actions: { allow: records.length } });
    }),

    route("POST", "/v1/chat/completions", "any", async ({ request, user }) => {
      const body = (await request.json()) as ChatCompletionRequest;
      const toolKey = request.headers.get("X-Aspida-Tool") ?? body.model;
      const tool = state.tools.find((candidate) => candidate.slug === toolKey || candidate.domains.includes(toolKey));
      if (!tool) return problem(404, `"${toolKey}" is not in the AI tool inventory.`);

      const messages = body.messages.map((message) => ({ role: message.role, content: typeof message.content === "string" ? message.content : "" }));
      const prompt = messages.findLast((message) => message.role === "user")?.content ?? "";
      const { findings, categories } = detect(prompt, state);
      const found = foundItems(findings, categories);
      const { action, rule } = decidePrompt(tool.status, new Set(found.map((item) => item.data_type)));

      const conversationId = request.headers.get("X-Aspida-Conversation") ?? nextId(state, "conversation");
      const acknowledgedId = request.headers.get("X-Aspida-Acknowledge-Warning");
      const acknowledged = action === "warn" && acknowledgedId !== null && state.warnings.delete(acknowledgedId);
      const masks = action === "redact" || action === "warn";
      const forwarded = action === "allow" || action === "redact" || acknowledged;

      // Values enter the vault only when something is actually sent masked.
      const conversation = masks && forwarded ? conversationOf(state, conversationId, user.user_id) : { owner: user.user_id, placeholders: new Map(), counters: new Map() };
      const upstream = messages.map((message) => ({
        role: message.role,
        content: masks ? maskText(message.content, detect(message.content, state).findings, conversation).text : message.content,
      }));
      const masked = maskText(prompt, findings, conversation);
      const approved = state.tools.filter((candidate) => candidate.status === "approved" && candidate.is_demo);

      const trace: Trace = {
        trace_id: nextId(state, "trace"),
        conversation_id: conversationId,
        tool: { slug: tool.slug, name: tool.name, status: tool.status, category: tool.category, upstream_url: `http://mock-upstream:9000/tools/${tool.slug}/v1/chat/completions` },
        action,
        rule,
        policy_version: state.policies.find((policy) => policy.active)?.version ?? 1,
        explanation: explain(
          action,
          rule,
          tool,
          found,
          approved.map((candidate) => ({ slug: candidate.slug, name: candidate.name, status: candidate.status, category: candidate.category })),
          acknowledged,
        ),
        forwarded,
        needs_acknowledgement: action === "warn" && !acknowledged,
        upstream_messages: action === "block" ? [] : masks ? [{ role: "system", content: KEEP_PLACEHOLDERS }, ...upstream] : upstream,
        spans: masked.spans,
        tiers_run: ["T0", "T1", "T2"],
        timings_ms: { T0: 2.1 + prompt.length / 400, T1: 31 + prompt.length / 40, T2: 9.5 + prompt.length / 120 },
      };
      const headers = { "X-Aspida-Action": action, "X-Aspida-Rule": rule, "X-Aspida-Trace-Id": trace.trace_id };
      recordEvent(state, user, tool, trace, masked.text);

      if (!forwarded) {
        if (action === "warn") state.warnings.add(trace.trace_id);
        const refusal: PolicyErrorResponse = {
          error: { message: trace.explanation.summary, type: action === "warn" ? "aspida_policy_warning" : "aspida_policy_block", code: rule },
          aspida: trace,
        };
        return new Response(JSON.stringify(refusal), { status: action === "warn" ? 409 : 403, headers: { "Content-Type": "application/json", ...headers } });
      }

      const draft = draftReply(prompt, masks ? masked.text : "");
      const answer = restoreText(draft, conversation);
      const summary: TraceSummary = {
        trace_id: trace.trace_id,
        rehydration: {
          sent: masks ? new Set(trace.spans.flatMap((span) => (span.placeholder ? [span.placeholder] : []))).size : 0,
          returned: new Set(splitPlaceholders(draft).flatMap((part) => (part.kind === "placeholder" ? [part.text] : []))).size,
          unresolved: [],
        },
        usage: { input_tokens: Math.ceil(prompt.length / 4), output_tokens: Math.ceil(answer.length / 4), cost_usd: 0 },
        latency_ms: 180 + countPlaceholders(draft) * 3,
      };
      const envelope = { id: `chatcmpl-${trace.trace_id}`, model: body.model };

      if (!body.stream) {
        const completion = {
          ...envelope,
          object: "chat.completion",
          choices: [{ index: 0, message: { role: "assistant", content: answer }, finish_reason: "stop" }],
          aspida: trace,
          aspida_summary: summary,
        };
        return new Response(JSON.stringify(completion), { headers: { "Content-Type": "application/json", ...headers } });
      }
      const chunk = (fields: object) => `data: ${JSON.stringify({ ...envelope, object: "chat.completion.chunk", ...fields })}\n\n`;
      return eventStream(
        chunkedStream(
          [
            chunk({ choices: [], aspida: trace }),
            ...pieces(answer).map((content) => chunk({ choices: [{ index: 0, delta: { content }, finish_reason: null }] })),
            chunk({ choices: [{ index: 0, delta: {}, finish_reason: "stop" }] }),
            chunk({ choices: [], aspida_summary: summary }),
            "data: [DONE]\n\n",
          ],
          chunkDelayMs,
        ),
        headers,
      );
    }),
  ];
}
