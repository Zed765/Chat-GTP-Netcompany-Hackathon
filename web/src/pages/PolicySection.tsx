import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { gateway, unwrap } from "../api/client";
import { isAbort } from "../api/errors";
import type { InjectionProtection, PolicyOut, ValidationIssue } from "../api/types";
import { PolicyEditor, type PolicyEditorHandle } from "../features/policy/PolicyEditor";
import "../features/policy/policy.css";
import { useAction } from "../hooks/useAction";
import { useResource } from "../hooks/useResource";
import { plural } from "../lib/format";
import { PROTECTION } from "../lib/labels";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { Notice } from "../ui/Notice";
import { Setting, SettingNote, SettingPanel } from "../ui/Settings";
import { ErrorState } from "../ui/States";
import { Segmented } from "../ui/controls";

type Validation = { state: "checking" } | { state: "checked"; issues: ValidationIssue[] } | { state: "failed"; message: string };

/** Validates the draft a moment after the last keystroke; an older answer never overwrites a newer one. */
function useValidation(yaml: string | null): Validation {
  const [result, setResult] = useState<{ yaml: string; validation: Validation } | null>(null);

  useEffect(() => {
    if (yaml === null) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      unwrap(gateway.POST("/api/policy/validate", { body: { yaml }, signal: controller.signal }))
        .then(({ issues }) => setResult({ yaml, validation: { state: "checked", issues } }))
        .catch((error: unknown) => {
          if (!isAbort(error)) setResult({ yaml, validation: { state: "failed", message: error instanceof Error ? error.message : "Validation failed." } });
        });
    }, 400);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [yaml]);

  return result && result.yaml === yaml ? result.validation : { state: "checking" };
}

interface WorkbenchProps {
  active: PolicyOut;
  onActivated: (policy: PolicyOut) => void;
}

/** The rules, top to bottom in the order they are worked on: choose a version, draft or edit, check, activate. */
function Workbench({ active, onActivated }: WorkbenchProps) {
  const [draft, setDraft] = useState(active.yaml);
  // The version the text in the editor started from.
  const [shown, setShown] = useState(active.version);
  const [beforeDrafting, setBeforeDrafting] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const editor = useRef<PolicyEditorHandle>(null);
  const editorId = useId();
  const statusId = useId();
  const validation = useValidation(draft);
  const versions = useResource(`policy-versions:${active.version}`, (signal) => unwrap(gateway.GET("/api/policy/versions", { signal })));

  const issues = validation.state === "checked" ? validation.issues : [];
  const valid = validation.state === "checked" && issues.length === 0;
  const changed = draft !== active.yaml;

  const drafting = useAction(async (text: string) => {
    const result = await unwrap(gateway.POST("/api/policy/draft", { body: { instruction: text, yaml: draft } }));
    setBeforeDrafting(draft);
    setDraft(result.yaml);
    return result;
  });
  const activate = useAction(async () => {
    const policy = await unwrap(gateway.POST("/api/policy/activate", { body: { yaml: draft, note: null } }));
    setShown(policy.version);
    onActivated(policy);
    return policy;
  });
  const load = useAction(async (version: number) => {
    const policy = await unwrap(gateway.GET("/api/policy/versions/{version}", { params: { path: { version } } }));
    setDraft(policy.yaml);
    setShown(version);
  });

  function onDraft(event: FormEvent) {
    event.preventDefault();
    if (instruction.trim().length >= 3) void drafting.run(instruction.trim());
  }

  return (
    <>
      <div className="row">
        <select className="filter policy-version" aria-label="Version in the editor" value={shown} disabled={load.pending} onChange={(event) => void load.run(Number(event.target.value))}>
          {(versions.data ?? [active]).map((version) => (
            <option key={version.version} value={version.version}>
              Version {version.version}
              {version.active ? ", active" : ""}
              {version.note ? `: ${version.note}` : ""}
            </option>
          ))}
        </select>
        {changed && (
          <>
            <Badge hue="yellow">Draft, not active</Badge>
            <Button size="sm" variant="primary" icon="check" disabled={!valid} busy={activate.pending} onClick={() => void activate.run()}>
              Activate
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setDraft(active.yaml);
                setShown(active.version);
              }}
            >
              Discard changes
            </Button>
          </>
        )}
      </div>
      {load.error && (
        <Notice tone="danger" role="alert">
          {load.error.message}
        </Notice>
      )}

      <form className="policy-draft" onSubmit={onDraft}>
        <input
          className="input"
          aria-label="Describe a rule in plain language"
          placeholder="Describe a rule in plain language, for example: warn when Sales sends client names to a tolerated tool"
          value={instruction}
          maxLength={500}
          onChange={(event) => setInstruction(event.target.value)}
        />
        <Button type="submit" icon="plus" disabled={instruction.trim().length < 3} busy={drafting.pending}>
          Draft the rule
        </Button>
      </form>
      {drafting.error && (
        <Notice tone="danger" role="alert">
          {drafting.error.message}
        </Notice>
      )}
      {drafting.result && (
        <Notice
          tone={drafting.result.rule_name ? "info" : "warning"}
          title={drafting.result.rule_name ? `Rule “${drafting.result.rule_name}” added to the draft` : "No rule could be drafted from that"}
          role="status"
        >
          <span>{drafting.result.explanation}</span>
          {beforeDrafting !== null && (
            <span className="row">
              <Button
                size="sm"
                onClick={() => {
                  setDraft(beforeDrafting);
                  setBeforeDrafting(null);
                  drafting.reset();
                }}
              >
                Undo
              </Button>
            </span>
          )}
        </Notice>
      )}

      <div className="stack stack-sm">
        <label className="sr-only" htmlFor={editorId}>
          Policy document (YAML)
        </label>
        <PolicyEditor
          id={editorId}
          ref={editor}
          value={draft}
          onChange={setDraft}
          issueLines={new Set(issues.flatMap((issue) => (issue.line ? [issue.line] : [])))}
          describedBy={statusId}
          invalid={validation.state === "checked" && !valid}
        />
        <div id={statusId} role="status" className="stack stack-sm">
          {validation.state === "checking" && <span className="small muted">Checking the policy</span>}
          {validation.state === "failed" && <span className="error-text">The policy could not be checked: {validation.message}</span>}
          {valid && (
            <span className="row small secondary">
              <Icon name="check" size={14} />
              Valid
            </span>
          )}
          {issues.length > 0 && (
            <>
              <span className="row small">
                <Badge hue="red" icon="alert">
                  {plural(issues.length, "problem")}
                </Badge>
                Fix {issues.length === 1 ? "it" : "them"} before activating.
              </span>
              <ul className="issues">
                {issues.map((issue, index) => (
                  <li key={index}>
                    {issue.line ? (
                      <button type="button" className="link-btn" onClick={() => editor.current?.goToLine(issue.line ?? 1)}>
                        Line {issue.line}
                      </button>
                    ) : (
                      <span className="secondary">Document</span>
                    )}
                    <code>{issue.path}</code>
                    <span>{issue.message}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      {activate.error && (
        <Notice tone="danger" title="The policy was not activated" role="alert">
          {activate.error.message}
        </Notice>
      )}
      {activate.result && !changed && (
        <Notice tone="success" role="status">
          Version {activate.result.version} is active. It applies from the next request, with no restart.
        </Notice>
      )}
    </>
  );
}

const LEVELS: readonly InjectionProtection[] = ["off", "standard", "detailed"];

/** The rules, and how hard the gateway looks for hidden instructions in what the in-house agent reads. */
export function PolicySettings() {
  const policy = useResource("policy", (signal) => unwrap(gateway.GET("/api/policy", { signal })));
  // The level being saved shows as selected at once; it falls back if the save fails.
  const [saving, setSaving] = useState<InjectionProtection | null>(null);
  // The level is part of the policy, so saving it makes a new version. The editor starts again
  // from that version: activating older text would put the old level back.
  const [levelSaves, setLevelSaves] = useState(0);
  const protect = useAction(async (level: InjectionProtection) => {
    setSaving(level);
    try {
      policy.setData(await unwrap(gateway.PUT("/api/policy/injection-protection", { body: { level } })));
      setLevelSaves((count) => count + 1);
    } finally {
      setSaving(null);
    }
  });

  if (policy.status === "loading") return null;
  if (policy.status === "error") {
    return (
      <SettingNote>
        <ErrorState message={policy.error.message} onRetry={policy.reload} />
      </SettingNote>
    );
  }
  const active = policy.data;
  return (
    <>
      <SettingPanel label="Rules" value={`Version ${active.version}`}>
        <Workbench key={levelSaves} active={active} onActivated={policy.setData} />
      </SettingPanel>
      <Setting label="Agent injection protection">
        <Segmented
          legend="Agent injection protection"
          hideLegend
          options={LEVELS.map((value) => ({ value, label: PROTECTION[value].label }))}
          value={saving ?? active.injection_protection}
          onChange={(level) => void protect.run(level)}
          disabled={protect.pending}
        />
      </Setting>
      {protect.error && (
        <SettingNote>
          <Notice tone="danger" role="alert">
            {protect.error.message}
          </Notice>
        </SettingNote>
      )}
    </>
  );
}
