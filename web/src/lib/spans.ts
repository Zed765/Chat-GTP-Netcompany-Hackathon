export interface Range {
  start: number;
  end: number;
}

export interface Segment<S> {
  text: string;
  /** The span this run belongs to; `undefined` for text between spans. */
  span?: S;
}

const ASTRAL = /[\u{10000}-\u{10FFFF}]/u;

/**
 * The gateway counts offsets in Unicode code points (Python strings); JavaScript strings
 * index UTF-16 units. They differ once the text holds an emoji or another astral character.
 */
function codePointIndex(text: string): (offset: number) => number {
  if (!ASTRAL.test(text)) return (offset) => Math.min(offset, text.length);
  const starts: number[] = [];
  let unit = 0;
  for (const character of text) {
    starts.push(unit);
    unit += character.length;
  }
  starts.push(unit);
  return (offset) => starts[Math.min(offset, starts.length - 1)] ?? text.length;
}

/**
 * Cuts `text` into runs so that each span becomes its own run. Spans are taken in order of
 * start; one that overlaps an earlier span or is empty is skipped rather than drawn wrongly.
 */
export function segmentText<S extends Range>(text: string, spans: readonly S[]): Segment<S>[] {
  const toUnit = codePointIndex(text);
  const segments: Segment<S>[] = [];
  let cursor = 0;
  for (const span of [...spans].sort((a, b) => a.start - b.start)) {
    const start = toUnit(span.start);
    const end = toUnit(span.end);
    if (start < cursor || end <= start) continue;
    if (start > cursor) segments.push({ text: text.slice(cursor, start) });
    segments.push({ text: text.slice(start, end), span });
    cursor = end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor) });
  return segments;
}

export interface KnownValue {
  value: string;
  dataType: string;
}

/**
 * Finds the real values in a restored answer, so the reader sees what came back out of the
 * vault. Longer values win where one contains another ("Maria Papadopoulou" over "Maria").
 */
export function segmentRestored(text: string, values: readonly KnownValue[]): Segment<KnownValue>[] {
  const known = [...values].filter((item) => item.value.trim() !== "").sort((a, b) => b.value.length - a.value.length);
  const ranges: (Range & { value: KnownValue })[] = [];
  for (const item of known) {
    let from = text.indexOf(item.value);
    while (from !== -1) {
      const to = from + item.value.length;
      if (!ranges.some((range) => from < range.end && to > range.start)) {
        ranges.push({ start: from, end: to, value: item });
      }
      from = text.indexOf(item.value, to);
    }
  }
  const segments: Segment<KnownValue>[] = [];
  let cursor = 0;
  for (const range of ranges.sort((a, b) => a.start - b.start)) {
    if (range.start > cursor) segments.push({ text: text.slice(cursor, range.start) });
    segments.push({ text: text.slice(range.start, range.end), span: range.value });
    cursor = range.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor) });
  return segments;
}

/** The text of each span as the user typed it, for matching against the restored answer. */
export function spanValues<S extends Range & { data_type: string }>(text: string, spans: readonly S[]): KnownValue[] {
  return segmentText(text, spans).flatMap((segment) =>
    segment.span ? [{ value: segment.text, dataType: segment.span.data_type }] : [],
  );
}
