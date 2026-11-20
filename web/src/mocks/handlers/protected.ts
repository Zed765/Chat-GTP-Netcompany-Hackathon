import type {
  DocumentOut,
  GroupOut,
  ImportResult,
  PatternIn,
  PatternOut,
  ProtectedSummary,
  RowSource,
  Store,
  StoreSummary,
  TermOut,
  TermPage,
  TestResult,
} from "../../api/types";
import { CATEGORIES, CLIENTS, EMBEDDER_ID, PACK_VERSION, rowId } from "../fixtures/protected";
import { detect, toCodePoints } from "../detect";
import { type Handler, type Route, json, noContent, problem, route } from "../http";
import type { MockState } from "../state";
import { maskText } from "./chat";

type Row = { source: RowSource; enabled: boolean; group: string; data_type?: string | null };

function summarise(store: Store, rows: readonly Row[]): StoreSummary {
  const sources: RowSource[] = ["default", "synced", "uploaded", "seeded"];
  const groups = new Map<string, GroupOut>();
  for (const row of rows) {
    const key = `${row.source}/${row.group}`;
    const group = groups.get(key) ?? { group: row.group, source: row.source, data_type: row.data_type ?? null, rows: 0, enabled: false };
    group.rows += 1;
    group.enabled ||= row.enabled;
    groups.set(key, group);
  }
  return {
    store,
    layers: sources
      .map((source) => {
        const own = rows.filter((row) => row.source === source);
        return { source, rows: own.length, enabled: own.filter((row) => row.enabled).length };
      })
      .filter((layer) => layer.rows > 0 || layer.source === "default"),
    groups: [...groups.values()],
  };
}

const documentRows = (documents: readonly DocumentOut[]): Row[] =>
  documents.map((document) => ({ source: document.source, enabled: document.enabled, group: document.category, data_type: document.category }));

function parseTerms(name: string, text: string): { term: string; aliases: string[]; data_type: string }[] {
  if (name.endsWith(".json")) return JSON.parse(text) as { term: string; aliases: string[]; data_type: string }[];
  const [header, ...lines] = text.split(/\r?\n/).filter((line) => line.trim() !== "");
  const columns = (header ?? "").split(",").map((column) => column.trim().toLowerCase());
  return lines.map((line) => {
    const cells = line.split(",").map((cell) => cell.trim());
    const cell = (column: string) => cells[columns.indexOf(column)] ?? "";
    return { term: cell("term"), aliases: cell("aliases").split(/[;|]/).map((alias) => alias.trim()).filter(Boolean), data_type: cell("data_type") || "CLIENT" };
  });
}

function isRegex(source: string): boolean {
  try {
    return new RegExp(source) instanceof RegExp;
  } catch {
    return false;
  }
}

export function protectedRoutes(state: MockState): Route[] {
  const importTerms = (rows: readonly { term: string; aliases?: string[]; data_type?: string }[], source: RowSource, group: string): ImportResult => {
    const result: ImportResult = { imported: 0, duplicates: 0, errors: [] };
    rows.forEach((row, index) => {
      if (!row.term || row.term.length < 2) result.errors.push({ row: index + 1, message: "The term must be at least two characters long." });
      else if (state.terms.some((existing) => existing.term.toLowerCase() === row.term.toLowerCase())) result.duplicates += 1;
      else {
        state.terms.push({ id: rowId(), term: row.term, aliases: row.aliases ?? [], data_type: row.data_type ?? "CLIENT", source, group, enabled: true, created: new Date().toISOString() });
        result.imported += 1;
      }
    });
    return result;
  };

  const setEnabled =
    <T extends { id: string; enabled: boolean }>(rows: () => T[]): Handler =>
    async ({ params, request }) => {
      const row = rows().find((candidate) => candidate.id === params.id);
      if (!row) return problem(404, "Unknown row");
      row.enabled = ((await request.json()) as { enabled: boolean }).enabled;
      return json(row);
    };

  const remove =
    <T extends { id: string; source: RowSource }>(rows: () => T[], assign: (rows: T[]) => void): Handler =>
    ({ params }) => {
      const row = rows().find((candidate) => candidate.id === params.id);
      if (!row) return problem(404, "Unknown row");
      if (row.source === "default") return problem(409, "Default rows can be switched off but not deleted.");
      assign(rows().filter((candidate) => candidate !== row));
      return noContent();
    };

  return [
    route("GET", "/api/protected/summary", ["admin"], () => {
      const summary: ProtectedSummary = {
        pack_version: PACK_VERSION,
        embedder_id: EMBEDDER_ID,
        stale_documents: state.documents.filter((document) => document.stale).length,
        categories: [...CATEGORIES],
        data_types: [...new Set(["PERSON", "ORG", "LOCATION", "ADDRESS", "EMAIL", "PHONE", "AFM", "AMKA", "IBAN", "CARD", "ID_CARD", "SECRET", "CLIENT", "CONFIDENTIAL_MARKER", "CONTRACT", "FINANCIAL", "HEALTH", "HR", "SOURCE_CODE", "CLIENT_CONFIDENTIAL", ...state.terms.map((term) => term.data_type ?? "CLIENT"), ...state.patterns.map((pattern) => pattern.data_type)])],
        stores: [summarise("terms", state.terms), summarise("fingerprints", documentRows(state.documents)), summarise("patterns", state.patterns)],
      };
      return json(summary);
    }),

    route("GET", "/api/protected/terms", ["admin"], ({ url }) => {
      const query = url.searchParams;
      const needle = query.get("q")?.toLowerCase();
      const rows = state.terms.filter(
        (term) =>
          (!query.get("source") || term.source === query.get("source")) &&
          (!query.get("group") || term.group === query.get("group")) &&
          (!needle || [term.term, ...(term.aliases ?? [])].some((form) => form.toLowerCase().includes(needle))),
      );
      const offset = Number(query.get("offset") ?? 0);
      const page: TermPage = { total: rows.length, items: rows.slice(offset, offset + Number(query.get("limit") ?? 50)) };
      return json(page);
    }),
    route("POST", "/api/protected/terms", ["admin"], async ({ request }) => json(importTerms((await request.json()) as TermOut[], "uploaded", "uploaded-terms"))),
    route("POST", "/api/protected/terms/upload", ["admin"], async ({ request }) => {
      const file = (await request.formData()).get("file");
      if (!(file instanceof File)) return problem(422, "file: a CSV or JSON file is required");
      let rows: ReturnType<typeof parseTerms>;
      try {
        rows = parseTerms(file.name, await file.text());
      } catch {
        return problem(422, "The file could not be read as CSV or JSON.");
      }
      return json(importTerms(rows, "uploaded", "uploaded-terms"));
    }),
    route("POST", "/api/protected/terms/sync", ["admin"], () => json(importTerms(CLIENTS.map((client) => ({ term: client.term, aliases: [...client.aliases] })), "synced", "crm-clients"))),
    route("PATCH", "/api/protected/terms/:id", ["admin"], setEnabled(() => state.terms)),
    route("DELETE", "/api/protected/terms/:id", ["admin"], remove(() => state.terms, (rows) => (state.terms = rows))),

    route("PATCH", "/api/protected/groups/:store/:group", ["admin"], async ({ params, request }) => {
      const { enabled } = (await request.json()) as { enabled: boolean };
      const rows: { source: RowSource; enabled: boolean; group?: string; category?: string }[] =
        params.store === "terms" ? state.terms : params.store === "patterns" ? state.patterns : state.documents;
      const inGroup = rows.filter((row) => row.source === "default" && (row.group ?? row.category) === params.group);
      if (inGroup.length === 0) return problem(404, "Unknown group");
      for (const row of inGroup) row.enabled = enabled;
      return json(null);
    }),

    route("GET", "/api/protected/documents", ["admin"], ({ url }) =>
      json(state.documents.filter((document) => !url.searchParams.get("source") || document.source === url.searchParams.get("source"))),
    ),
    route("POST", "/api/protected/documents", ["admin"], async ({ request }) => {
      const form = await request.formData();
      const file = form.get("file");
      const label = String(form.get("label") ?? "");
      if (!(file instanceof File)) return problem(422, "file: a document is required");
      if (file.size > 10 * 1024 * 1024) return problem(413, "The file is larger than 10 MB.");
      if (label.length < 2) return problem(422, "label: give the document a label of at least two characters");
      const existing = state.documents.find((document) => document.label === label);
      if (existing) return json({ document: existing, duplicate: true });
      const document: DocumentOut = {
        id: rowId(),
        label,
        category: String(form.get("category") ?? "CLIENT_CONFIDENTIAL"),
        language: null,
        source: "uploaded",
        chunks: Math.max(1, Math.ceil(file.size / 900)),
        embedder_id: EMBEDDER_ID,
        stale: false,
        enabled: true,
        created: new Date().toISOString(),
      };
      state.documents.push(document);
      return json({ document, duplicate: false });
    }),
    route("PATCH", "/api/protected/documents/:id", ["admin"], setEnabled(() => state.documents)),
    route("DELETE", "/api/protected/documents/:id", ["admin"], remove(() => state.documents, (rows) => (state.documents = rows))),

    route("GET", "/api/protected/patterns", ["admin"], ({ url }) =>
      json(state.patterns.filter((pattern) => !url.searchParams.get("source") || pattern.source === url.searchParams.get("source"))),
    ),
    route("POST", "/api/protected/patterns", ["admin"], async ({ request }) => {
      const input = (await request.json()) as PatternIn;
      if (!isRegex(input.regex)) return problem(422, "regex: this expression is not valid.");
      // RE2 has no lookaround or backreferences; the gateway rejects them, so the mock does too.
      if (/\(\?<?[=!]|\\[1-9]/.test(input.regex)) return problem(422, "regex: lookarounds and backreferences are not supported, so that matching time stays linear.");
      const pattern: PatternOut = { ...input, id: rowId(), source: "uploaded", group: "custom-patterns", enabled: true, created: new Date().toISOString() };
      state.patterns.push(pattern);
      return json(pattern);
    }),
    route("PATCH", "/api/protected/patterns/:id", ["admin"], setEnabled(() => state.patterns)),
    route("DELETE", "/api/protected/patterns/:id", ["admin"], remove(() => state.patterns, (rows) => (state.patterns = rows))),

    route("POST", "/api/protected/patterns/assist", ["admin"], () =>
      json({ added: [], message: "The preview has no model behind it. In the app, AI adds this from your description." }),
    ),

    route("POST", "/api/protected/test", ["admin"], async ({ request }) => {
      const { text } = (await request.json()) as { text: string };
      const { findings, categories } = detect(text, state);
      const masked = maskText(text, findings, { owner: "", placeholders: new Map(), counters: new Map() });
      const placeholders = masked.spans.filter((span) => span.placeholder !== null);
      const result: TestResult = {
        masked_text: masked.text,
        findings: findings.map((finding) => ({
          data_type: finding.dataType,
          start: toCodePoints(text, finding.start),
          end: toCodePoints(text, finding.end),
          placeholder: finding.masked ? (placeholders.shift()?.placeholder ?? null) : null,
          tier: finding.tier,
          score: finding.tier === "T0" ? 1 : 0.88,
          recogniser: finding.recogniser,
          encoded: false,
          masked: finding.masked,
          store: finding.store,
          source: finding.source,
          match_label: finding.matchLabel,
        })),
        categories: categories.map((category) => ({
          category: category.category,
          tier: category.tier,
          score: category.score,
          conclusive: category.conclusive,
          evidence: category.evidence,
          store: category.store,
          source: category.source,
          match_label: category.matchLabel,
        })),
        tiers_run: ["T0", "T1", "T2"],
        timings_ms: { T0: 2.3, T1: 36.4, T2: 10.8 },
        notes: text.length < 160 ? ["The text is too short for fingerprint matching (under about 40 tokens), so only patterns, names and terms were checked."] : [],
      };
      return json(result);
    }),

    route("POST", "/api/protected/demo-data/remove", ["admin"], () => {
      const demo = (row: { source: RowSource }) => row.source === "seeded" || row.source === "synced";
      const removed = { terms: state.terms.filter(demo).length, documents: state.documents.filter(demo).length, patterns: state.patterns.filter(demo).length };
      state.terms = state.terms.filter((row) => !demo(row));
      state.documents = state.documents.filter((row) => !demo(row));
      state.patterns = state.patterns.filter((row) => !demo(row));
      return json(removed);
    }),
  ];
}
