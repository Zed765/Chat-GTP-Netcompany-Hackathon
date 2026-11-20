import { type FormEvent, useState } from "react";
import { gateway, unwrap } from "../api/client";
import type { AgentTrust } from "../api/types";
import { useAction } from "../hooks/useAction";
import { useResource } from "../hooks/useResource";
import { AGENT_SYSTEMS } from "../lib/labels";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { Notice } from "../ui/Notice";
import { Setting, SettingNote } from "../ui/Settings";
import { ErrorState } from "../ui/States";
import { Segmented } from "../ui/controls";

const TRUST = [
  { value: "trusted", label: "Trusted" },
  { value: "untrusted", label: "Untrusted" },
] as const;

/**
 * The systems the in-house agent reaches. What a trusted system returns is believed, and real
 * values may be sent to it. Email is judged by its recipients: it carries real values only
 * when every one of them is on a listed domain. A change applies to the agent's next tool call.
 */
export function AgentToolSettings() {
  const trust = useResource("agent-trust", (signal) => unwrap(gateway.GET("/api/agent/trust", { signal })));
  const [domain, setDomain] = useState("");
  const save = useAction(async (next: Pick<AgentTrust, "mail_domains"> & { trusted_servers: string[] }) => {
    trust.setData(await unwrap(gateway.PUT("/api/agent/trust", { body: next })));
  });

  if (trust.status === "loading") return null;
  if (trust.status === "error") {
    return (
      <SettingNote>
        <ErrorState message={trust.error.message} onRetry={trust.reload} />
      </SettingNote>
    );
  }
  const { systems, mail_domains: domains } = trust.data;
  const trusted = systems.filter((system) => system.trusted).map((system) => system.server);
  const setTrusted = (server: string, on: boolean) => void save.run({ trusted_servers: on ? [...trusted, server] : trusted.filter((name) => name !== server), mail_domains: domains });
  const setDomains = (next: string[]) => save.run({ trusted_servers: trusted, mail_domains: next });

  async function onAdd(event: FormEvent) {
    event.preventDefault();
    const wanted = domain.trim().toLowerCase().replace(/^@/, "");
    if (wanted === "") return;
    if (!domains.includes(wanted)) await setDomains([...domains, wanted]);
    setDomain("");
  }

  return (
    <>
      {systems.map((system) => (
        <Setting
          key={system.server}
          label={
            <>
              <span className="status-dot" data-hue={system.trusted ? "green" : "yellow"} />
              {AGENT_SYSTEMS[system.server] ?? system.server}
            </>
          }
        >
          <Segmented
            legend={`Trust in ${AGENT_SYSTEMS[system.server] ?? system.server}`}
            hideLegend
            options={TRUST}
            value={system.trusted ? "trusted" : "untrusted"}
            onChange={(value) => setTrusted(system.server, value === "trusted")}
            disabled={save.pending}
          />
        </Setting>
      ))}
      <Setting label="Email real values to">
        <ul className="domains">
          {domains.map((name) => (
            <li key={name}>
              {name}
              <button type="button" aria-label={`Remove ${name}`} disabled={save.pending} onClick={() => void setDomains(domains.filter((other) => other !== name))}>
                <Icon name="close" size={12} />
              </button>
            </li>
          ))}
        </ul>
        <form className="domain-add" onSubmit={(event) => void onAdd(event)}>
          <input className="input" aria-label="Domain to add" placeholder="example.com" value={domain} maxLength={253} spellCheck={false} autoCapitalize="off" onChange={(event) => setDomain(event.target.value)} />
          <Button type="submit" size="sm" icon="plus" disabled={domain.trim() === "" || save.pending}>
            Add
          </Button>
        </form>
      </Setting>
      {save.error && (
        <SettingNote>
          <Notice tone="danger" role="alert">
            {save.error.message}
          </Notice>
        </SettingNote>
      )}
    </>
  );
}
