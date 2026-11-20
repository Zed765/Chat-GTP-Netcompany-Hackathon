import type { DocumentOut, PatternOut, RowSource, Store, TermOut, Tier } from "../api/types";

/** A stand-in for the gateway's detectors: enough to exercise the UI, not a detector to trust. */
export interface Detected {
  start: number;
  end: number;
  text: string;
  dataType: string;
  tier: Tier;
  recogniser: string;
  /** Mentions with the same key share one placeholder ("Maria" and "Μαρία Παπαδοπούλου"). */
  entity: string;
  masked: boolean;
  store: Store | null;
  source: RowSource | null;
  matchLabel: string | null;
}

export interface DetectedCategory {
  category: string;
  tier: Tier;
  score: number;
  conclusive: boolean;
  evidence: string;
  store: Store | null;
  source: RowSource | null;
  matchLabel: string | null;
}

export interface Stores {
  terms: readonly TermOut[];
  documents: readonly DocumentOut[];
  patterns: readonly PatternOut[];
}

const BUILT_IN: readonly { dataType: string; recogniser: string; regex: RegExp }[] = [
  { dataType: "IBAN", recogniser: "iban", regex: /\bGR\d{2}(?: ?\d{4}){5} ?\d{3}\b/g },
  { dataType: "EMAIL", recogniser: "email", regex: /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g },
  { dataType: "PHONE", recogniser: "phone", regex: /(?:\+30 ?)?\b(?:2\d{2}|69\d) ?\d{3} ?\d{4}\b/g },
  { dataType: "AMKA", recogniser: "amka", regex: /\b\d{11}\b/g },
  { dataType: "AFM", recogniser: "afm", regex: /\b\d{9}\b/g },
];

const PEOPLE: readonly { entity: string; forms: readonly string[] }[] = [
  {
    entity: "maria-papadopoulou",
    forms: ["Maria Papadopoulou", "Μαρία Παπαδοπούλου", "Μαρίας Παπαδοπούλου", "Ms Papadopoulou", "κα Παπαδοπούλου"],
  },
  { entity: "nikos-antoniou", forms: ["Nikos Antoniou", "Νίκος Αντωνίου", "Νίκου Αντωνίου"] },
  { entity: "dimitris-karagiannis", forms: ["Dimitris Karagiannis", "Δημήτρης Καραγιάννης"] },
];

const CATEGORY_CUES: readonly { category: string; regex: RegExp; evidence: string }[] = [
  { category: "CONTRACT", regex: /hereinafter|governed by the laws|shall not exceed|συμβαλλόμεν|η παρούσα σύμβαση/i, evidence: "resembles a contract" },
  { category: "FINANCIAL", regex: /\bEBITDA\b|\brevenue\b|profit margin|τα έσοδα|κερδοφορία/i, evidence: "resembles a financial document" },
  { category: "SOURCE_CODE", regex: /^\s*(?:def |class |import |function |const |#include )/m, evidence: "resembles source code" },
];

const fold = (value: string) => value.toLocaleLowerCase("el").normalize("NFD").replace(/\p{M}/gu, "");

function occurrences(haystack: string, needle: string): number[] {
  const found: number[] = [];
  const target = fold(needle);
  // Folding keeps one code unit per letter for Greek and Latin, so indexes still line up.
  const text = fold(haystack);
  if (target.length < 2 || text.length !== haystack.length) return found;
  let from = text.indexOf(target);
  while (from !== -1) {
    found.push(from);
    from = text.indexOf(target, from + target.length);
  }
  return found;
}

function compile(pattern: PatternOut): RegExp | null {
  try {
    return new RegExp(pattern.regex, "g");
  } catch {
    return null;
  }
}

export function detect(text: string, stores: Stores): { findings: Detected[]; categories: DetectedCategory[] } {
  const candidates: Detected[] = [];
  const add = (start: number, length: number, rest: Omit<Detected, "start" | "end" | "text">) =>
    candidates.push({ start, end: start + length, text: text.slice(start, start + length), ...rest });

  for (const pattern of stores.patterns.filter((row) => row.enabled)) {
    const regex = compile(pattern);
    for (const match of regex ? text.matchAll(regex) : []) {
      add(match.index, match[0].length, {
        dataType: pattern.data_type,
        tier: "T0",
        recogniser: `pattern:${pattern.name}`,
        entity: match[0],
        masked: true,
        store: "patterns",
        source: pattern.source,
        matchLabel: pattern.name,
      });
    }
  }
  for (const { dataType, recogniser, regex } of BUILT_IN) {
    for (const match of text.matchAll(regex)) {
      add(match.index, match[0].length, {
        dataType,
        tier: "T0",
        recogniser,
        entity: match[0].replaceAll(" ", ""),
        masked: true,
        store: null,
        source: null,
        matchLabel: null,
      });
    }
  }
  for (const row of stores.terms.filter((term) => term.enabled && term.group !== "greek-given-names" && term.group !== "greek-surnames")) {
    for (const form of [row.term, ...(row.aliases ?? [])]) {
      for (const start of occurrences(text, form)) {
        add(start, form.length, {
          dataType: row.data_type ?? "CLIENT",
          tier: "T1",
          recogniser: "terms",
          entity: row.term,
          masked: row.data_type !== "CONFIDENTIAL_MARKER",
          store: "terms",
          source: row.source,
          matchLabel: row.group,
        });
      }
    }
  }
  for (const person of PEOPLE) {
    for (const form of person.forms) {
      for (const start of occurrences(text, form)) {
        add(start, form.length, {
          dataType: "PERSON",
          tier: "T1",
          recogniser: /\p{Script=Greek}/u.test(form) ? "ner:el" : "ner:en",
          entity: person.entity,
          masked: true,
          store: null,
          source: null,
          matchLabel: null,
        });
      }
    }
  }

  // Longest match wins where candidates overlap; ties go to the earlier recogniser.
  const findings: Detected[] = [];
  for (const candidate of candidates.sort((a, b) => b.end - b.start - (a.end - a.start) || a.start - b.start)) {
    if (!findings.some((kept) => candidate.start < kept.end && candidate.end > kept.start)) findings.push(candidate);
  }
  findings.sort((a, b) => a.start - b.start);

  const categories: DetectedCategory[] = [];
  const fingerprint = stores.documents.find(
    (document) => document.enabled && document.source !== "default" && document.label.includes("Helios") && /Master Services Agreement/i.test(text),
  );
  if (fingerprint) {
    categories.push({
      category: fingerprint.category,
      tier: "T2",
      score: 0.91,
      conclusive: true,
      evidence: `matches "${fingerprint.label}"`,
      store: "fingerprints",
      source: fingerprint.source,
      matchLabel: fingerprint.label,
    });
  }
  for (const cue of CATEGORY_CUES) {
    if (cue.regex.test(text) && !categories.some((found) => found.category === cue.category)) {
      categories.push({
        category: cue.category,
        tier: "T2",
        score: 0.74,
        conclusive: false,
        evidence: cue.evidence,
        store: "fingerprints",
        source: "default",
        matchLabel: `exemplars: ${cue.category.toLowerCase()}`,
      });
    }
  }
  return { findings, categories };
}

/** The gateway reports offsets in code points; this converts from JavaScript's UTF-16 units. */
export function toCodePoints(text: string, unit: number): number {
  return [...text.slice(0, unit)].length;
}
