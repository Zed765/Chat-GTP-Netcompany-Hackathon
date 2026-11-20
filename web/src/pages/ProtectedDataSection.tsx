import { type FormEvent, type KeyboardEvent, useState } from "react";
import { gateway, unwrap } from "../api/client";
import type { ProtectedSummary, StoreSummary, TestResult } from "../api/types";
import { DocumentsPanel, PatternsPanel, TermsPanel } from "../features/protected/stores";
import "../features/chat/chat.css";
import "../features/protected/protected.css";
import { useAction } from "../hooks/useAction";
import { useResource } from "../hooks/useResource";
import { formatNumber, plural } from "../lib/format";
import { textLang } from "../lib/lang";
import { TypeChip } from "../ui/Badge";
import { Button } from "../ui/Button";
import { ConfirmDialog } from "../ui/Dialog";
import { Notice } from "../ui/Notice";
import { PlaceholderText, TypedText } from "../ui/SensitiveText";
import { Setting, SettingNote, SettingPanel } from "../ui/Settings";
import { ErrorState } from "../ui/States";

function TestOutcome({ text, result }: { text: string; result: TestResult }) {
  return (
    <div className="stack" role="status">
      <div className="grid" style={{ "--min": "20rem" } as React.CSSProperties}>
        <div className="stack stack-sm">
          <h3>What was recognised</h3>
          <div className="test-text">
            <TypedText text={text} spans={result.findings} />
          </div>
        </div>
        <div className="stack stack-sm">
          <h3>What an AI tool would see</h3>
          <div className="test-text">
            <PlaceholderText text={result.masked_text} />
          </div>
        </div>
      </div>

      {result.findings.length === 0 && result.categories.length === 0 && <Notice tone="success">Nothing sensitive was found in this text.</Notice>}
      {/* A kind of document marks no single value, so the boxes above cannot show it. */}
      {result.categories.length > 0 && (
        <p className="row small">
          Recognised as
          {[...new Set(result.categories.map((category) => category.category))].map((category) => (
            <TypeChip key={category} type={category} />
          ))}
        </p>
      )}
      {result.notes.map((note) => (
        <p key={note} className="hint">
          {note}
        </p>
      ))}
    </div>
  );
}

/** Try a text against detection: what is found in it, and which term, document or pattern matched. */
function TestPrompt() {
  const [text, setText] = useState("");
  const test = useAction(async (value: string) => ({ text: value, result: await unwrap(gateway.POST("/api/protected/test", { body: { text: value } })) }));

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (text.trim() !== "" && !test.pending) void test.run(text);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter tests; Shift + Enter starts a new line. Enter that confirms an input-method choice does neither.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  return (
    <>
      <form className="composer" onSubmit={onSubmit}>
        <textarea
          className="composer-input"
          rows={1}
          aria-label="Text to test"
          value={text}
          lang={textLang(text)}
          maxLength={50_000}
          placeholder="Paste a prompt. Enter to test, Shift + Enter for a new line"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
        />
      </form>
      {test.error && (
        <Notice tone="danger" role="alert">
          {test.error.message}
        </Notice>
      )}
      {test.result && <TestOutcome text={test.result.text} result={test.result.result} />}
    </>
  );
}

/** The demo organisation's rows, with the one thing to do about them. Absent when there are none. */
function DemoData({ summary, onRemoved }: { summary: ProtectedSummary; onRemoved: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const remove = useAction(async () => {
    const result = await unwrap(gateway.POST("/api/protected/demo-data/remove"));
    setConfirming(false);
    onRemoved();
    return result;
  });
  const demoRows = summary.stores.flatMap((store) => store.layers).filter((layer) => layer.source === "seeded" || layer.source === "synced");
  const count = demoRows.reduce((sum, layer) => sum + layer.rows, 0);

  if (count === 0 && !remove.result && !remove.error) return null;
  return (
    <>
      {count > 0 && (
        <Setting label="Demo data">
          <span className="setting-value">{plural(count, "row")}</span>
          <Button size="sm" icon="trash" onClick={() => setConfirming(true)}>
            Remove
          </Button>
        </Setting>
      )}
      {remove.error && (
        <SettingNote>
          <Notice tone="danger" role="alert">
            {remove.error.message}
          </Notice>
        </SettingNote>
      )}
      {remove.result && (
        <SettingNote>
          <Notice tone="success" role="status">
            Removed {plural(remove.result.terms, "term")}, {plural(remove.result.documents, "document")} and {plural(remove.result.patterns, "pattern")}. Detection now runs on the default pack and
            anything you uploaded.
          </Notice>
        </SettingNote>
      )}
      <ConfirmDialog open={confirming} title="Remove the demo organisation's data?" confirmLabel="Remove demo data" busy={remove.pending} onConfirm={() => void remove.run()} onClose={() => setConfirming(false)}>
        <p>
          This deletes {plural(count, "row")}: the demo clients synced from the mock CRM, the demo documents' fingerprints and the demo pattern. Client names from the demo will no longer be
          recognised. Restarting the stack with demo data loads them again.
        </p>
      </ConfirmDialog>
    </>
  );
}

/** What detection matches against: terms, document fingerprints and patterns, and a place to try a text against them. */
export function ProtectedDataSettings() {
  const summary = useResource("protected-summary", (signal) => unwrap(gateway.GET("/api/protected/summary", { signal })));
  const [removals, setRemovals] = useState(0);

  if (summary.status === "loading") return null;
  if (summary.status === "error") {
    return (
      <SettingNote>
        <ErrorState message={summary.error.message} onRetry={summary.reload} />
      </SettingNote>
    );
  }
  const data = summary.data;
  const store = (key: StoreSummary["store"]) => data.stores.find((item) => item.store === key) ?? { store: key, layers: [], groups: [] };
  const rows = (key: StoreSummary["store"]) => formatNumber(store(key).layers.reduce((sum, layer) => sum + layer.rows, 0));
  return (
    <>
      {data.stale_documents > 0 && (
        <SettingNote>
          <Notice tone="warning" title={`${plural(data.stale_documents, "document")} must be uploaded again`}>
            The embedder changed since {data.stale_documents === 1 ? "it was" : "they were"} fingerprinted. Uploaded text is never kept, so it cannot be re-embedded automatically.
          </Notice>
        </SettingNote>
      )}
      {/* The panels are keyed by removals, so their lists reload after demo data is removed. */}
      <SettingPanel label="Terms" value={rows("terms")}>
        <TermsPanel key={removals} summary={store("terms")} onChanged={summary.reload} />
      </SettingPanel>
      <SettingPanel label="Document fingerprints" value={rows("fingerprints")}>
        <DocumentsPanel key={removals} summary={store("fingerprints")} categories={data.categories} onChanged={summary.reload} />
      </SettingPanel>
      <SettingPanel label="Patterns" value={rows("patterns")}>
        <PatternsPanel key={removals} summary={store("patterns")} dataTypes={data.data_types} onChanged={summary.reload} />
      </SettingPanel>
      <SettingPanel label="Test a prompt">
        <TestPrompt />
      </SettingPanel>
      <DemoData
        summary={data}
        onRemoved={() => {
          summary.reload();
          setRemovals((value) => value + 1);
        }}
      />
    </>
  );
}
