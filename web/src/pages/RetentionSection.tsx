import { type FormEvent, useState } from "react";
import { gateway, unwrap } from "../api/client";
import { useAction } from "../hooks/useAction";
import { useResource } from "../hooks/useResource";
import { Button } from "../ui/Button";
import { Notice } from "../ui/Notice";
import { Setting, SettingNote } from "../ui/Settings";

const MAX_DAYS = 3650;

/** How long events are kept before they are deleted: a number of days, typed and saved. */
export function RetentionSetting() {
  const settings = useResource("privacy-settings", (signal) => unwrap(gateway.GET("/api/privacy/settings", { signal })));
  // What is being typed; null while the field shows the saved period.
  const [typed, setTyped] = useState<string | null>(null);
  const save = useAction(async (days: number, snippets: boolean) => {
    settings.setData(await unwrap(gateway.PUT("/api/privacy/settings", { body: { retention_days: days, store_snippets: snippets } })));
    setTyped(null);
  });
  const data = settings.data;
  const problem = settings.error ?? save.error;
  const days = Number(typed);
  const valid = typed !== null && Number.isInteger(days) && days >= 1 && days <= MAX_DAYS;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (data && valid && days !== data.retention_days) void save.run(days, data.store_snippets);
  }

  return (
    <>
      {data && (
        <Setting label="Keep events for">
          <form className="retention" onSubmit={onSubmit}>
            <input
              className="input"
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_DAYS}
              aria-label="Days to keep events"
              value={typed ?? data.retention_days}
              onChange={(event) => setTyped(event.target.value)}
            />
            <span className="setting-value">days</span>
            {typed !== null && days !== data.retention_days && (
              <Button type="submit" size="sm" variant="primary" disabled={!valid} busy={save.pending}>
                Save
              </Button>
            )}
          </form>
        </Setting>
      )}
      {problem && (
        <SettingNote>
          <Notice tone="danger" role="alert">
            {problem.message}
          </Notice>
        </SettingNote>
      )}
    </>
  );
}
