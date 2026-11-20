import { type Hue, dataTypeInfo } from "../../lib/dataTypes";
import { plural } from "../../lib/format";
import { textLang } from "../../lib/lang";
import { type KnownValue, segmentRestored } from "../../lib/spans";
import { Button } from "../../ui/Button";
import { Markdown } from "../../ui/Markdown";
import { Notice } from "../../ui/Notice";
import { PlaceholderText, RestoredText, TypedText } from "../../ui/SensitiveText";
import type { Turn } from "./turns";
import type { Masked } from "./vault";

/** Whose side of the firewall the conversation is shown from. */
export type Side = "you" | "tool";

/** The answer as the tool wrote it: each value that was restored, shown as its placeholder again. */
function AsWritten({ text, values, placeholders }: { text: string; values: readonly KnownValue[]; placeholders: ReadonlyMap<string, string> }) {
  return (
    <span className="prewrap" lang={textLang(text)}>
      {segmentRestored(text, values).map((segment, index) => {
        const placeholder = segment.span && placeholders.get(segment.text);
        if (!segment.span || !placeholder) return <span key={index}>{segment.text}</span>;
        const info = dataTypeInfo(segment.span.dataType);
        return (
          <span key={index} className="chip tinted" data-hue={info.hue} title={`Placeholder for: ${info.label}`}>
            {placeholder}
          </span>
        );
      })}
    </span>
  );
}

function outcome(turn: Turn, masked: number): { hue: Hue; text: string } {
  if (!turn.trace) return { hue: "neutral", text: "Checking" };
  if (turn.status === "blocked") return { hue: "red", text: "Blocked" };
  if (turn.status === "warned") return { hue: "yellow", text: "Waiting for your decision" };
  if (turn.status === "cancelled") return { hue: "neutral", text: "Cancelled, nothing was sent" };
  if (masked === 0 || turn.trace.action === "allow") return { hue: "green", text: "Sent as written" };
  return { hue: "blue", text: `${plural(masked, "value")} masked` };
}

interface TurnViewProps {
  turn: Turn;
  /** Every value masked in the conversation up to and including this turn. */
  known: readonly Masked[];
  /** Set for the whole conversation, by the one switch above it. */
  side: Side;
  busy: boolean;
  onAcknowledge: () => void;
  onCancel: () => void;
  onRetry: () => void;
}

/**
 * One exchange: the message, a line saying what the firewall did, and the answer. Seen from
 * the AI tool's side, each masked value is replaced by its placeholder in place. That includes
 * a later answer that brings back a value an earlier message put in the vault.
 */
export function TurnView({ turn, known, side, busy, onAcknowledge, onCancel, onRetry }: TurnViewProps) {
  const { trace } = turn;
  const masked = new Set(trace?.spans.flatMap((span) => (span.placeholder ? [span.placeholder] : []))).size;
  const placeholders = new Map(known.map((item) => [item.value, item.placeholder]));
  const seen = trace?.upstream_messages.findLast((message) => message.role === "user")?.content;
  const look = outcome(turn, masked);
  const answered = turn.status === "streaming" || turn.status === "done";

  return (
    <>
      <li id={`turn-${turn.id}`} className="message message-user">
        {/* Keyed by side, so the swapped values draw themselves in again when the view flips. */}
        <div key={side} className="swap">
          {side === "tool" && seen !== undefined ? <PlaceholderText text={seen} /> : <TypedText text={turn.prompt} spans={trace?.spans ?? []} />}
        </div>
      </li>

      <li className="firewall" data-hue={look.hue} title={trace?.explanation.summary}>
        <span className="row">
          <span className="tool-dot" />
          {look.text}
        </span>
      </li>

      {turn.status === "failed" && (
        <li>
          <Notice tone="danger" title="This message could not be sent" role="alert">
            <span>{turn.error}</span>
            <span>
              <Button size="sm" icon="refresh" onClick={onRetry} busy={busy}>
                Try again
              </Button>
            </span>
          </Notice>
        </li>
      )}
      {trace && turn.status === "warned" && (
        <li className="row" role="group" aria-label="Your decision">
          <Button variant="primary" icon="mask" busy={busy} onClick={onAcknowledge}>
            Send the masked version
          </Button>
          <Button onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        </li>
      )}
      {trace && turn.status === "blocked" && (
        <li className="row" role="group" aria-label="Your decision">
          <Button variant="primary" icon="mask" busy={busy} onClick={onAcknowledge}>
            Send with placeholders anyway
          </Button>
        </li>
      )}

      {answered && (
        <li className="message message-assistant" lang={textLang(turn.answer)}>
          {turn.answer === "" ? (
            <span className="muted">Working</span>
          ) : (
            <div key={side} className="swap">
              <Markdown
                text={turn.answer}
                leaf={(text) => (side === "tool" ? <AsWritten text={text} values={known} placeholders={placeholders} /> : <RestoredText text={text} values={known} />)}
              />
            </div>
          )}
          {turn.status === "streaming" && <span className="caret" aria-hidden="true" />}
        </li>
      )}
    </>
  );
}
