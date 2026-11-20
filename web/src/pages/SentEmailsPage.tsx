import { useNavigate } from "react-router";
import { gateway, unwrap } from "../api/client";
import { useAction } from "../hooks/useAction";
import { useResource } from "../hooks/useResource";
import { formatDateTime } from "../lib/format";
import { Button } from "../ui/Button";
import { Notice } from "../ui/Notice";
import { PageHeader } from "../ui/PageHeader";
import { PlaceholderText } from "../ui/SensitiveText";
import { EmptyState, ResourceView } from "../ui/States";

/** The emails the agent sent to addresses outside the organisation, exactly as they arrived. */
export default function SentEmailsPage() {
  const navigate = useNavigate();
  const inbox = useResource("attacker-inbox", (signal) => unwrap(gateway.GET("/api/demo/attacker-inbox", { signal })), { pollMs: 4000 });
  const clear = useAction(async () => {
    await unwrap(gateway.DELETE("/api/demo/attacker-inbox"));
    inbox.setData([]);
  });

  return (
    <div className="page">
      <PageHeader
        title="Sent emails"
        actions={
          <>
            <Button icon="refresh" onClick={inbox.reload}>
              Refresh
            </Button>
            <Button icon="trash" busy={clear.pending} disabled={(inbox.data ?? []).length === 0} onClick={() => void clear.run()}>
              Clear
            </Button>
          </>
        }
      />
      {clear.error && (
        <Notice tone="danger" role="alert">
          {clear.error.message}
        </Notice>
      )}
      <ResourceView
        resource={inbox}
        label="the sent emails"
        isEmpty={(messages) => messages.length === 0}
        empty={
          <EmptyState icon="send" title="Nothing has been sent" action={<Button variant="primary" onClick={() => void navigate("/agent")}>Open the agent</Button>} />
        }
      >
        {(messages) => (
          <ul className="mailbox">
            {messages.map((message) => {
              return (
                <li key={message.id} className="card mail">
                  <header className="mail-header">
                    <h2 className="wrap-anywhere">{message.subject || "(no subject)"}</h2>
                    <span className="small muted nowrap">{formatDateTime(message.received)}</span>
                  </header>
                  <dl className="kv small">
                    <dt>From</dt>
                    <dd>{message.sender}</dd>
                    <dt>To</dt>
                    <dd>{message.recipient}</dd>
                  </dl>
                  <div className="mail-body">
                    <PlaceholderText text={message.body} />
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </ResourceView>
    </div>
  );
}
