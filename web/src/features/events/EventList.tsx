import { gateway, unwrap } from "../../api/client";
import type { EventOut } from "../../api/types";
import { useAction } from "../../hooks/useAction";
import { dataTypeInfo } from "../../lib/dataTypes";
import { formatDateTime, formatRecent } from "../../lib/format";
import { ACTIONS, CHANNELS, TOOL_STATUS } from "../../lib/labels";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { PlaceholderText } from "../../ui/SensitiveText";

function dataFound(event: EventOut): string {
  return Object.entries(event.data_counts)
    .map(([type, count]) => (count > 1 ? `${dataTypeInfo(type).label} ×${count}` : dataTypeInfo(type).label))
    .join(", ");
}

/** What the row cannot say in a word, as sentences. */
function remarks(event: EventOut, sensitive: boolean): string[] {
  const lines: string[] = [];
  if (event.origin === "log") {
    lines.push("Found in an uploaded log: this request went around the firewall and reached the tool as written. The outcome is what the policy would have done.");
  } else if (event.sent_unmasked && sensitive) {
    lines.push("The policy let this data reach the tool unmasked.");
  }
  if (event.injection_flagged) lines.push("This content was flagged as a prompt injection.");
  if (event.tainted) lines.push("The agent had read untrusted content earlier in this session.");
  return lines;
}

/** Who sent one event: looked up for that event alone, and shown in place. */
function Sender({ eventId }: { eventId: number }) {
  const lookup = useAction(() => unwrap(gateway.GET("/api/events/{event_id}/identity", { params: { path: { event_id: eventId } } })));
  if (lookup.result) {
    return (
      <span>
        {lookup.result.display_name}, {lookup.result.team} <span className="muted">({lookup.result.user_id})</span>
      </span>
    );
  }
  return (
    <span className="row">
      <Button size="sm" icon="eye" busy={lookup.pending} onClick={() => void lookup.run()}>
        Show who sent this
      </Button>
      {lookup.error && (
        <span className="error-text" role="alert">
          {lookup.error.message}
        </span>
      )}
    </span>
  );
}

interface EventRowProps {
  event: EventOut;
  /** Human names for tool slugs, where the caller has them. */
  toolNames?: ReadonlyMap<string, string>;
}

/** One event as one line; it opens to the masked text, the rule and who sent it. */
function EventRow({ event, toolNames }: EventRowProps) {
  const outcome = ACTIONS[event.action];
  const found = dataFound(event);
  const byAgent = event.channel !== "prompt";
  const status = !byAgent && event.tool_status ? TOOL_STATUS[event.tool_status] : null;
  const target = event.agent_tool ?? (event.tool ? (toolNames?.get(event.tool) ?? event.tool) : "Unknown");
  const note = [byAgent ? CHANNELS[event.channel] : status?.label, event.origin === "log" ? "from a log" : null].filter(Boolean).join(", ");
  return (
    <li className="event">
      <details>
        <summary className="event-line">
          <time className="event-time" dateTime={event.ts}>
            {formatRecent(event.ts)}
          </time>
          <span className="event-team">{event.team}</span>
          <span className="event-cell event-target">
            {status && <span className="event-dot" data-hue={status.hue} />}
            <span className="wrap-anywhere">{target}</span>
            {/* The dot's colour says the tool's status; the words are kept for screen readers only. */}
            {note && <span className="sr-only">{note}</span>}
          </span>
          <span className="event-cell event-outcome">
            <span className="event-dot" data-hue={outcome.hue} />
            {outcome.past}
            {event.injection_flagged && <span className="event-flag">Injection flagged</span>}
          </span>
          <span className={found ? "event-data" : "event-data muted"}>{found || "Nothing sensitive"}</span>
          <Icon name="chevron-right" size={14} />
        </summary>
        <div className="event-detail">
          {event.masked_snippet && (
            <p className="event-snippet">
              <PlaceholderText text={event.masked_snippet} />
            </p>
          )}
          {remarks(event, found !== "").map((line) => (
            <p key={line} className="event-remark">
              {line}
            </p>
          ))}
          <dl className="kv small">
            <dt>When</dt>
            <dd>{formatDateTime(event.ts)}</dd>
            <dt>Rule</dt>
            <dd>
              <code className="rule-name">{event.rule}</code> <span className="muted">in policy version {event.policy_version}</span>
            </dd>
            <dt>Sent by</dt>
            <dd>
              <Sender eventId={event.id} />
            </dd>
          </dl>
        </div>
      </details>
    </li>
  );
}

/** Events as the gateway records them: no text beyond a masked snippet, and no names until one is asked for. */
export function EventList({ events, toolNames }: { events: readonly EventOut[]; toolNames?: ReadonlyMap<string, string> }) {
  return (
    <div className="events">
      <div className="event-line events-head" aria-hidden="true">
        <span>Time</span>
        <span>Team</span>
        <span>Sent to</span>
        <span>Outcome</span>
        <span>Data found</span>
      </div>
      <ul>
        {events.map((event) => (
          <EventRow key={event.id} event={event} toolNames={toolNames} />
        ))}
      </ul>
    </div>
  );
}
