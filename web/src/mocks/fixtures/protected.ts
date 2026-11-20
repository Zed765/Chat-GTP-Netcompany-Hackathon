import type { DocumentOut, PatternOut, RowSource, TermOut } from "../../api/types";
import { DAY_MS, isoMinus } from "./org";

export const PACK_VERSION = "2026.11.1";
export const EMBEDDER_ID = "local-hash-ngram-2048";

let nextId = 0;

/** Row ids shaped like the gateway's UUIDs. */
export function rowId(): string {
  nextId += 1;
  return `00000000-0000-4000-8000-${nextId.toString(16).padStart(12, "0")}`;
}

const MARKERS = [
  ["Confidential", "Strictly confidential", "Company confidential"],
  ["Internal use only", "For internal use only"],
  ["Attorney-client privileged", "Privileged and confidential"],
  ["Do not distribute", "Not for distribution"],
  ["Trade secret"],
  ["Εμπιστευτικό", "Αυστηρά εμπιστευτικό"],
  ["Απόρρητο", "Άκρως απόρρητο"],
  ["Για εσωτερική χρήση", "Μόνο για εσωτερική χρήση"],
  ["Δικηγορικό απόρρητο"],
  ["Να μην κοινοποιηθεί"],
] as const;

const GIVEN_NAMES = [
  ["Μαρία", "Μαρίας", "Maria"],
  ["Γιώργος", "Γιώργου", "Giorgos"],
  ["Ελένη", "Ελένης", "Eleni"],
  ["Νίκος", "Νίκου", "Nikos"],
  ["Κατερίνα", "Κατερίνας", "Katerina"],
  ["Δημήτρης", "Δημήτρη", "Dimitris"],
  ["Αναστασία", "Αναστασίας", "Anastasia"],
  ["Κώστας", "Κώστα", "Kostas"],
] as const;

const SURNAMES = [
  ["Παπαδόπουλος", "Παπαδοπούλου", "Papadopoulos"],
  ["Γεωργίου", "Γεωργίου", "Georgiou"],
  ["Αντωνίου", "Αντωνίου", "Antoniou"],
  ["Καραγιάννης", "Καραγιάννη", "Karagiannis"],
  ["Οικονόμου", "Οικονόμου", "Oikonomou"],
  ["Βασιλείου", "Βασιλείου", "Vasileiou"],
] as const;

/** Clients of the demo organisation, as the mock CRM would supply them. */
export const CLIENTS = [
  { term: "Helios Shipping S.A.", aliases: ["Helios Shipping", "Ήλιος Ναυτιλιακή Α.Ε.", "Ήλιος Ναυτιλιακή", "Ilios Naftiliaki"] },
  { term: "Aegean Foods Ltd", aliases: ["Aegean Foods", "Αιγαίο Τρόφιμα ΕΠΕ", "Aigaio Trofima"] },
  { term: "Olympus Insurance", aliases: ["Όλυμπος Ασφαλιστική", "Olympos Asfalistiki"] },
  { term: "Kyklades Energy S.A.", aliases: ["Kyklades Energy", "Κυκλάδες Ενεργειακή Α.Ε."] },
  { term: "Thessaly Logistics", aliases: ["Θεσσαλία Logistics", "ThesLog"] },
  { term: "Attica Medical Group", aliases: ["Αττική Ιατρικός Όμιλος", "AMG"] },
  { term: "Ionian Hotels & Resorts", aliases: ["Ionian Hotels", "Ιόνιο Ξενοδοχειακή"] },
  { term: "Pindos Dairy Cooperative", aliases: ["Pindos Dairy", "Συνεταιρισμός Πίνδος"] },
] as const;

const PROJECTS = ["Project Atlas", "Project Meltemi", "Project Kerberos"] as const;

function term(
  value: string,
  aliases: readonly string[],
  dataType: string,
  source: RowSource,
  group: string,
  created: string,
): TermOut {
  return { id: rowId(), term: value, aliases: [...aliases], data_type: dataType, source, group, enabled: true, created };
}

export function buildTerms(now: Date): TermOut[] {
  const shipped = isoMinus(now, 30 * DAY_MS);
  const synced = isoMinus(now, 14 * DAY_MS);
  return [
    ...MARKERS.map(([first, ...rest]) => term(first, rest, "CONFIDENTIAL_MARKER", "default", "confidentiality-markers", shipped)),
    ...GIVEN_NAMES.map(([first, ...rest]) => term(first, rest, "PERSON", "default", "greek-given-names", shipped)),
    ...SURNAMES.map(([first, ...rest]) => term(first, rest, "PERSON", "default", "greek-surnames", shipped)),
    ...CLIENTS.map((client) => term(client.term, client.aliases, "CLIENT", "synced", "crm-clients", synced)),
    ...PROJECTS.map((name) => term(name, [name.replace("Project ", "")], "PROJECT", "seeded", "project-names", synced)),
  ];
}

/** The categories a protected document can be filed under. */
export const CATEGORIES = ["CLIENT_CONFIDENTIAL", "CONTRACT", "FINANCIAL", "HEALTH", "HR", "SOURCE_CODE"] as const;

const EXEMPLAR_CATEGORIES = ["CONTRACT", "FINANCIAL", "HEALTH", "HR", "SOURCE_CODE"] as const;

const CORPUS = [
  ["MSA – Helios Shipping (2026)", "CONTRACT", "en", 14],
  ["Σύμβαση παροχής υπηρεσιών – Αιγαίο Τρόφιμα", "CONTRACT", "el", 11],
  ["NDA – Kyklades Energy", "CONTRACT", "en", 6],
  ["SOW – Aegean Foods ERP migration", "CLIENT_CONFIDENTIAL", "en", 9],
  ["Πρόταση συνεργασίας – Όλυμπος Ασφαλιστική", "CLIENT_CONFIDENTIAL", "el", 8],
  ["Q3 2026 financial summary", "FINANCIAL", "en", 7],
  ["Οικονομική ανασκόπηση 2025", "FINANCIAL", "el", 10],
  ["Board meeting notes, September 2026", "CLIENT_CONFIDENTIAL", "en", 5],
  ["atlas/billing/reconcile.py", "SOURCE_CODE", null, 4],
  ["meltemi/api/routes.ts", "SOURCE_CODE", null, 6],
] as const;

export function buildDocuments(now: Date): DocumentOut[] {
  const shipped = isoMinus(now, 30 * DAY_MS);
  const seeded = isoMinus(now, 14 * DAY_MS);
  const exemplars = EXEMPLAR_CATEGORIES.flatMap((category) =>
    [1, 2, 3, 4].map((number): DocumentOut => ({
      id: rowId(),
      label: `Exemplar: ${category.toLowerCase().replace("_", " ")} ${number}`,
      category,
      language: category === "SOURCE_CODE" ? null : number % 2 === 0 ? "el" : "en",
      source: "default",
      chunks: 3 + ((number * 7) % 4),
      embedder_id: EMBEDDER_ID,
      stale: false,
      enabled: true,
      created: shipped,
    })),
  );
  const corpus = CORPUS.map(([label, category, language, chunks]): DocumentOut => ({
    id: rowId(),
    label,
    category,
    language,
    source: "seeded",
    chunks,
    embedder_id: EMBEDDER_ID,
    stale: false,
    enabled: true,
    created: seeded,
  }));
  return [...exemplars, ...corpus];
}

const PROVIDER_PATTERNS = [
  ["OpenAI API key", String.raw`\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b`],
  ["GitHub personal access token", String.raw`\bgh[pousr]_[A-Za-z0-9]{36,}\b`],
  ["AWS access key ID", String.raw`\b(?:AKIA|ASIA)[0-9A-Z]{16}\b`],
  ["Stripe secret key", String.raw`\b[sr]k_live_[A-Za-z0-9]{24,}\b`],
  ["Slack token", String.raw`\bxox[abprs]-[A-Za-z0-9-]{10,}\b`],
  ["Google API key", String.raw`\bAIza[0-9A-Za-z_-]{35}\b`],
  ["Private key block", String.raw`-{5}BEGIN [A-Z ]*PRIVATE KEY-{5}`],
  ["Database connection string", String.raw`\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s:@/]+:[^\s@/]+@[^\s/]+`],
  ["JSON Web Token", String.raw`\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b`],
] as const;

export function buildPatterns(now: Date): PatternOut[] {
  const shipped = isoMinus(now, 30 * DAY_MS);
  return [
    ...PROVIDER_PATTERNS.map(([name, regex]): PatternOut => ({
      id: rowId(),
      name,
      regex,
      data_type: "SECRET",
      source: "default",
      group: "provider-keys",
      enabled: true,
      created: shipped,
    })),
    {
      id: rowId(),
      name: "Project code",
      regex: String.raw`\bPRJ-[A-Z]{3,8}-\d{4}\b`,
      data_type: "PROJECT",
      source: "seeded",
      group: "project-codes",
      enabled: true,
      created: isoMinus(now, 14 * DAY_MS),
    },
  ];
}
