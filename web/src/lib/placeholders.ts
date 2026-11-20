/** `<PERSON_1>`, `<ID_CARD_2>`, a company's own `<ΕΡΓΟ_3>`, and the one-way `<SECRET_REDACTED>`. */
const PLACEHOLDER = /<(?:(\p{Lu}[\p{Lu}\p{Nd}_]*?)_\d+|SECRET_REDACTED)>/gu;

export type TextPart =
  | { kind: "text"; text: string }
  | { kind: "placeholder"; text: string; dataType: string };

/** Splits masked text into plain runs and placeholders, in order. */
export function splitPlaceholders(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let cursor = 0;
  for (const match of text.matchAll(PLACEHOLDER)) {
    if (match.index > cursor) parts.push({ kind: "text", text: text.slice(cursor, match.index) });
    parts.push({ kind: "placeholder", text: match[0], dataType: match[1] ?? "SECRET" });
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) parts.push({ kind: "text", text: text.slice(cursor) });
  return parts;
}

export function countPlaceholders(text: string): number {
  return text.match(PLACEHOLDER)?.length ?? 0;
}
