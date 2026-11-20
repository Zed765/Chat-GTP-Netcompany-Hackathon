import { dataTypeInfo } from "../lib/dataTypes";
import { textLang } from "../lib/lang";
import { splitPlaceholders } from "../lib/placeholders";
import { type KnownValue, type Range, segmentRestored, segmentText } from "../lib/spans";

interface TypedSpan extends Range {
  data_type: string;
  placeholder?: string | null;
  /** False for a finding that is flagged but left in place. Defaults to whether there is a placeholder. */
  masked?: boolean;
}

/**
 * The text as typed, with each detected span highlighted in the hue of its data type. A span
 * that is flagged but not masked (a confidentiality marker) gets a dashed outline instead.
 */
export function TypedText({ text, spans }: { text: string; spans: readonly TypedSpan[] }) {
  return (
    <span className="prewrap" lang={textLang(text)}>
      {segmentText(text, spans).map((segment, index) => {
        if (!segment.span) return <span key={index}>{segment.text}</span>;
        const info = dataTypeInfo(segment.span.data_type);
        const flagged = !(segment.span.masked ?? Boolean(segment.span.placeholder));
        return (
          <mark
            key={index}
            className={flagged ? "mark mark-flag tinted" : "mark tinted"}
            data-hue={info.hue}
            title={flagged ? `${info.label}: flagged, not masked` : segment.span.placeholder ? `${info.label} → ${segment.span.placeholder}` : info.label}
          >
            {segment.text}
            <span className="sr-only"> ({flagged ? `${info.label}, flagged but not masked` : info.label})</span>
          </mark>
        );
      })}
    </span>
  );
}

/** Masked text, with every placeholder drawn as a chip in the hue of its data type. */
export function PlaceholderText({ text }: { text: string }) {
  return (
    <span className="prewrap" lang={textLang(text)}>
      {splitPlaceholders(text).map((part, index) => {
        if (part.kind === "text") return <span key={index}>{part.text}</span>;
        const info = dataTypeInfo(part.dataType);
        return (
          <span key={index} className="chip tinted" data-hue={info.hue} title={`Placeholder for: ${info.label}`}>
            {part.text}
          </span>
        );
      })}
    </span>
  );
}

/** A restored answer, with the values that came back out of the vault highlighted. */
export function RestoredText({ text, values }: { text: string; values: readonly KnownValue[] }) {
  return (
    <span className="prewrap" lang={textLang(text)}>
      {segmentRestored(text, values).map((segment, index) => {
        if (!segment.span) return <span key={index}>{segment.text}</span>;
        const info = dataTypeInfo(segment.span.dataType);
        return (
          <mark key={index} className="mark tinted" data-hue={info.hue} title={`Restored: ${info.label}`}>
            {segment.text}
            <span className="sr-only"> (restored {info.label})</span>
          </mark>
        );
      })}
    </span>
  );
}
