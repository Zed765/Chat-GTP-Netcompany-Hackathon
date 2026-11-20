import type { ToolResultEvent } from "../../api/types";
import type { Hue } from "../../lib/dataTypes";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { PlaceholderText } from "../../ui/SensitiveText";
import type { Activity } from "./session";

/** The colour of the dot: the most serious thing that happened to this call. */
function hueOf({ call, result }: Activity, decided: "approved" | "rejected" | undefined): Hue {
  if (result?.injection?.flagged) return "red";
  if (call) {
    const { action, resolved, needs_confirmation } = call.decision;
    if (decided === "rejected" || action === "block") return "red";
    if (needs_confirmation && decided !== "approved") return "yellow";
    if (!resolved && action === "redact") return "blue";
  }
  return result?.source === "untrusted" ? "yellow" : "green";
}

function Argument({ value }: { value: unknown }) {
  return typeof value === "string" ? <PlaceholderText text={value} /> : <code>{JSON.stringify(value)}</code>;
}

function FlaggedSpan({ text }: { text: string }) {
  return (
    <mark className="mark tinted flagged-span" data-hue="red">
      <span className="sr-only">Flagged as an injection: </span>
      <PlaceholderText text={text} />
    </mark>
  );
}

/**
 * The masked result with the flagged span marked inside it. The preview is shortened, so the
 * span is often past its end; it is then shown on its own, below the preview.
 */
function Preview({ result }: { result: ToolResultEvent }) {
  const evidence = result.injection?.flagged ? result.injection.evidence : null;
  const at = evidence ? result.preview.indexOf(evidence) : -1;
  if (!evidence) return <PlaceholderText text={result.preview} />;
  if (at === -1) {
    return (
      <>
        <PlaceholderText text={result.preview} />
        <span className="flagged-apart">
          <span className="activity-label">Flagged text, further down in this result</span>
          <FlaggedSpan text={evidence} />
        </span>
      </>
    );
  }
  return (
    <>
      <PlaceholderText text={result.preview.slice(0, at)} />
      <FlaggedSpan text={evidence} />
      <PlaceholderText text={result.preview.slice(at + evidence.length)} />
    </>
  );
}

interface ActivityRowProps {
  activity: Activity;
  decided: "approved" | "rejected" | undefined;
  /** The call is held until the user decides, so the row opens by itself to show the buttons. */
  awaiting: boolean;
  busy: boolean;
  onConfirm: (approve: boolean) => void;
}

/** One tool call in the conversation: a line with the tool's name that opens to what was sent and what came back. */
export function ActivityRow({ activity, decided, awaiting, busy, onConfirm }: ActivityRowProps) {
  const { call, result } = activity;
  const sent = Object.entries(call?.arguments ?? {});
  return (
    <li className="activity" data-hue={hueOf(activity, decided)}>
      <details open={awaiting}>
        <summary>
          <span className="activity-dot" />
          <code>{activity.tool}</code>
          <Icon name="chevron-right" size={14} />
        </summary>
        <div className="activity-body">
          {sent.length > 0 && (
            <div>
              <span className="activity-label">Sent</span>
              <dl className="kv small activity-arguments">
                {sent.map(([key, value]) => (
                  <div key={key} className="activity-argument">
                    <dt>{key}</dt>
                    <dd>
                      <Argument value={value} />
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
          {result && (
            <div>
              <span className="activity-label">Returned</span>
              <div className="activity-preview">
                <Preview result={result} />
              </div>
            </div>
          )}
          {result?.injection?.flagged && (
            <p className="activity-alert tinted" data-hue="red" role="alert">
              <Icon name="alert" />
              <span>
                <strong>Prompt injection detected.</strong> The marked text is treated as data, not as an instruction.
              </span>
            </p>
          )}
          {awaiting && (
            <div className="row" role="group" aria-label={`Confirm ${activity.tool}`}>
              <Button variant="primary" size="sm" icon="check" busy={busy} onClick={() => onConfirm(true)}>
                Approve and send
              </Button>
              <Button size="sm" disabled={busy} onClick={() => onConfirm(false)}>
                Reject
              </Button>
            </div>
          )}
        </div>
      </details>
    </li>
  );
}
