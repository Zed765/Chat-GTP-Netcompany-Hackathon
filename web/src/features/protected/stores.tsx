import { type FormEvent, type ReactNode, useId, useRef, useState } from "react";
import { asFormData, gateway, unwrap } from "../../api/client";
import type { GroupOut, ImportResult, RowSource, Store, StoreSummary } from "../../api/types";
import { useAction } from "../../hooks/useAction";
import { useResource } from "../../hooks/useResource";
import { dataTypeInfo } from "../../lib/dataTypes";
import { formatDate, plural } from "../../lib/format";
import { STORES } from "../../lib/labels";
import { SourceBadge, TypeChip } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { Notice } from "../../ui/Notice";
import { EmptyState, ResourceView } from "../../ui/States";
import { Field, Pagination, Switch } from "../../ui/controls";
import { TableWrap } from "../../ui/TableWrap";

interface PanelProps {
  summary: StoreSummary;
  /** Call after any change, so the counts and the other panels stay in step. */
  onChanged: () => void;
}

const SOURCE_FILTERS: readonly { value: RowSource | ""; label: string }[] = [
  { value: "", label: "All rows" },
  { value: "default", label: "Default pack" },
  { value: "synced", label: "Synced from CRM" },
  { value: "uploaded", label: "Uploaded" },
  { value: "seeded", label: "Demo organisation" },
];

function SourceFilter({ value, onChange }: { value: RowSource | ""; onChange: (value: RowSource | "") => void }) {
  return (
    <Field label="Show">
      {({ id }) => (
        <select id={id} className="select" value={value} onChange={(event) => onChange(event.target.value as RowSource | "")}>
          {SOURCE_FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

/**
 * The default pack: one switch for all of it, and its groups, each with a switch of its own, folded
 * away until asked for. Defaults can be switched off but not edited or deleted.
 */
function DefaultGroups({ store, groups, onChanged }: { store: Store; groups: readonly GroupOut[]; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const defaults = groups.filter((group) => group.source === "default");
  const set = (group: string, enabled: boolean) => unwrap(gateway.PATCH("/api/protected/groups/{store}/{group}", { params: { path: { store, group } }, body: { enabled } }));
  const toggle = useAction(async (group: string, enabled: boolean) => {
    await set(group, enabled);
    onChanged();
  });
  const toggleAll = useAction(async (enabled: boolean) => {
    await Promise.all(defaults.filter((group) => group.enabled !== enabled).map((group) => set(group.group, enabled)));
    onChanged();
  });
  const busy = toggle.pending || toggleAll.pending;
  const problem = toggle.error ?? toggleAll.error;

  if (defaults.length === 0) return null;
  return (
    <div className="stack stack-sm">
      <div className="pack-head">
        <button type="button" className="pack-toggle" aria-expanded={open} aria-controls={listId} onClick={() => setOpen((shown) => !shown)}>
          <Icon name="chevron-right" size={14} />
          Default pack
        </button>
        {/* On while any group is on; switching it turns every group on or off. */}
        <Switch checked={defaults.some((group) => group.enabled)} label="Use the default pack" disabled={busy} onChange={(enabled) => void toggleAll.run(enabled)} />
      </div>
      <ul id={listId} className="groups" hidden={!open}>
        {defaults.map((group) => (
          <li key={group.group}>
            <Switch checked={group.enabled} label={`Use the default group ${group.group}`} disabled={busy} onChange={(enabled) => void toggle.run(group.group, enabled)} />
            <span className="grow">
              <strong>{group.group.replaceAll("-", " ").replaceAll("_", " ").toLowerCase()}</strong> <span className="small secondary">({plural(group.rows, STORES[store].unit)})</span>
            </span>
          </li>
        ))}
      </ul>
      {problem && (
        <Notice tone="danger" role="alert">
          {problem.message}
        </Notice>
      )}
    </div>
  );
}

function ImportOutcome({ result, noun }: { result: ImportResult; noun: string }) {
  return (
    <Notice tone={result.errors.length > 0 ? "warning" : "success"} role="status">
      <span>
        {plural(result.imported, noun)} imported, {plural(result.duplicates, "duplicate")} skipped
        {result.errors.length > 0 ? `, ${plural(result.errors.length, "row")} rejected:` : ". Detection uses them from the next request."}
      </span>
      {result.errors.length > 0 && (
        <ul className="small">
          {result.errors.map((error) => (
            <li key={error.row}>
              Row {error.row}: {error.message}
            </li>
          ))}
        </ul>
      )}
    </Notice>
  );
}

interface RowControlsProps {
  source: RowSource;
  enabled: boolean;
  name: string;
  busy: boolean;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}

/** A default row gets a switch; a company row can be deleted. */
function RowControls({ source, enabled, name, busy, onToggle, onDelete }: RowControlsProps) {
  return source === "default" ? (
    <Switch checked={enabled} label={`Use ${name}`} disabled={busy} onChange={onToggle} />
  ) : (
    <Button size="sm" icon="trash" disabled={busy} aria-label={`Delete ${name}`} onClick={onDelete}>
      Delete
    </Button>
  );
}

function ActionError({ error }: { error: { message: string } | null }): ReactNode {
  return error ? (
    <Notice tone="danger" role="alert">
      {error.message}
    </Notice>
  ) : null;
}

const PAGE_SIZE = 5;

const ASSIST_HINT = "Describe a format and AI writes the pattern";

/** Describe a format in plain words, and the model writes the pattern. The gateway checks and tries it before it is kept. */
function PatternAssist({ onAdded }: { onAdded: () => void }) {
  const [request, setRequest] = useState("");
  // A request that added nothing goes along with the next one, so "only after the word address" is understood.
  const [previous, setPrevious] = useState<{ request: string; message: string } | null>(null);
  const ask = useAction(async (text: string) => {
    const result = await unwrap(gateway.POST("/api/protected/patterns/assist", { body: { request: text, previous } }));
    if (result.added.length > 0) {
      setRequest("");
      setPrevious(null);
      onAdded();
    } else {
      setPrevious({ request: text, message: result.message.slice(0, 1000) });
    }
    return result;
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (request.trim().length >= 3) void ask.run(request.trim());
  }

  return (
    <div className="stack stack-sm">
      <form className="assist" onSubmit={onSubmit}>
        <input className="input" aria-label={ASSIST_HINT} placeholder={ASSIST_HINT} value={request} maxLength={500} onChange={(event) => setRequest(event.target.value)} />
        <Button type="submit" icon="bot" disabled={request.trim().length < 3} busy={ask.pending}>
          Add with AI
        </Button>
      </form>
      <ActionError error={ask.error} />
      {ask.result && (
        <Notice tone={ask.result.added.length > 0 ? "success" : "warning"} role="status">
          {ask.result.message}
        </Notice>
      )}
    </div>
  );
}

function SearchField({ value, placeholder, onChange }: { value: string; placeholder: string; onChange: (value: string) => void }) {
  return (
    <Field label="Search">
      {({ id }) => <input id={id} className="input" type="search" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />}
    </Field>
  );
}

/** One page of a list the gateway returns whole: the rows whose text holds the search, from `offset`. */
function pageOf<T>(items: readonly T[], search: string, offset: number, text: (item: T) => string) {
  const query = search.trim().toLocaleLowerCase();
  const found = query ? items.filter((item) => text(item).toLocaleLowerCase().includes(query)) : items;
  // A search or a deletion can leave the offset past the end: show the last page instead.
  const start = Math.min(offset, Math.max(0, Math.ceil(found.length / PAGE_SIZE) - 1) * PAGE_SIZE);
  return { rows: found.slice(start, start + PAGE_SIZE), total: found.length, start };
}

export function TermsPanel({ summary, onChanged }: PanelProps) {
  const [source, setSource] = useState<RowSource | "">("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState("");
  const terms = useResource(`terms:${source}:${search}:${offset}`, (signal) =>
    unwrap(gateway.GET("/api/protected/terms", { params: { query: { source: source || undefined, q: search.trim() || undefined, offset, limit: PAGE_SIZE } }, signal })),
  );
  const refresh = () => {
    terms.reload();
    onChanged();
  };
  const upload = useAction(async (file: File) => {
    // The generated type describes a file field as a string; the form serializer sends the File itself.
    const result = await unwrap(gateway.POST("/api/protected/terms/upload", { body: { file: file as unknown as string }, bodySerializer: asFormData }));
    refresh();
    return result;
  });
  const sync = useAction(async () => {
    const result = await unwrap(gateway.POST("/api/protected/terms/sync"));
    refresh();
    return result;
  });
  const change = useAction(async (id: string, enabled: boolean | null) => {
    if (enabled === null) await unwrap(gateway.DELETE("/api/protected/terms/{term_id}", { params: { path: { term_id: id } } }));
    else await unwrap(gateway.PATCH("/api/protected/terms/{term_id}", { params: { path: { term_id: id } }, body: { enabled } }));
    refresh();
  });

  function onUpload(event: FormEvent) {
    event.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (file) void upload.run(file);
  }

  return (
    <>
      <DefaultGroups store="terms" groups={summary.groups} onChanged={refresh} />

      <div className="stack stack-sm">
        <h3 className="add-heading">
          Add company terms{" "}
          <span>
            A CSV or JSON file with a <code>term</code> column and optional <code>aliases</code> and <code>data_type</code>.
          </span>
        </h3>
        <form className="row" onSubmit={onUpload}>
          <div className="field">
            <input
              ref={fileInput}
              className="input"
              type="file"
              aria-label="Term list (CSV or JSON)"
              accept=".csv,.json,text/csv,application/json"
              onChange={(event) => setFileName(event.target.files?.[0]?.name ?? "")}
            />
          </div>
          <Button type="submit" icon="upload" disabled={fileName === ""} busy={upload.pending}>
            Import
          </Button>
          <Button icon="refresh" busy={sync.pending} onClick={() => void sync.run()}>
            Sync from CRM
          </Button>
        </form>
        <ActionError error={upload.error ?? sync.error} />
        {upload.result && <ImportOutcome result={upload.result} noun="term" />}
        {sync.result && <ImportOutcome result={sync.result} noun="term" />}
      </div>

      <div className="stack stack-sm">
        <div className="row">
          <SourceFilter
            value={source}
            onChange={(value) => {
              setSource(value);
              setOffset(0);
            }}
          />
          <SearchField
            value={search}
            placeholder="Term or alias"
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
          />
        </div>
        <ActionError error={change.error} />
        <ResourceView resource={terms} label="terms" isEmpty={(page) => page.items.length === 0} empty={<EmptyState title="No terms match">Change the filter, or import a term list.</EmptyState>}>
          {(page) => (
            <div className="stack stack-sm">
              <TableWrap>
                <table className="table table-stack table-fixed">
                  <thead>
                    <tr>
                      <th scope="col">Term</th>
                      <th scope="col" className="col-type">
                        Data type
                      </th>
                      <th scope="col" className="col-layer">
                        Layer
                      </th>
                      <th scope="col" className="col-use">
                        Use or remove
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((term) => (
                      <tr key={term.id}>
                        <th scope="row" data-label="Term" className="wrap-anywhere" title={term.aliases?.length ? `${term.term}. Also matches: ${term.aliases.join(", ")}` : term.term}>
                          {term.term}
                        </th>
                        <td data-label="Data type">
                          <TypeChip type={term.data_type ?? "CLIENT"} />
                        </td>
                        <td data-label="Layer">
                          <SourceBadge source={term.source} />
                        </td>
                        <td data-label="Use or remove">
                          <RowControls
                            source={term.source}
                            enabled={term.enabled}
                            name={term.term}
                            busy={change.pending}
                            onToggle={(enabled) => void change.run(term.id, enabled)}
                            onDelete={() => void change.run(term.id, null)}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
              <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onChange={setOffset} />
            </div>
          )}
        </ResourceView>
      </div>
    </>
  );
}

export function DocumentsPanel({ summary, categories, onChanged }: PanelProps & { categories: readonly string[] }) {
  const [source, setSource] = useState<RowSource | "">("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [label, setLabel] = useState("");
  const [category, setCategory] = useState(categories[0] ?? "");
  const fileInput = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState("");
  const documents = useResource(`documents:${source}`, (signal) => unwrap(gateway.GET("/api/protected/documents", { params: { query: { source: source || undefined } }, signal })));
  const refresh = () => {
    documents.reload();
    onChanged();
  };
  const upload = useAction(async (file: File) => {
    const result = await unwrap(
      gateway.POST("/api/protected/documents", { body: { file: file as unknown as string, label: label.trim(), category, source: "uploaded" }, bodySerializer: asFormData }),
    );
    setLabel("");
    refresh();
    return result;
  });
  const change = useAction(async (id: string, enabled: boolean | null) => {
    if (enabled === null) await unwrap(gateway.DELETE("/api/protected/documents/{document_id}", { params: { path: { document_id: id } } }));
    else await unwrap(gateway.PATCH("/api/protected/documents/{document_id}", { params: { path: { document_id: id } }, body: { enabled } }));
    refresh();
  });

  function onUpload(event: FormEvent) {
    event.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (file && label.trim().length >= 2) void upload.run(file);
  }

  return (
    <>
      <DefaultGroups store="fingerprints" groups={summary.groups} onChanged={refresh} />

      <div className="stack stack-sm">
        <p className="small secondary">Add a document and prompts that quote it are recognised; its text is not kept.</p>
        <form className="row" onSubmit={onUpload}>
          <Field
            label={
              <>
                Document <span className="label-note">(text, Markdown, PDF or Word)</span>
              </>
            }
          >
            {({ id }) => <input id={id} ref={fileInput} className="input" type="file" onChange={(event) => setFileName(event.target.files?.[0]?.name ?? "")} />}
          </Field>
          <Field label="Label">
            {({ id, describedBy }) => <input id={id} className="input" value={label} maxLength={200} aria-describedby={describedBy} onChange={(event) => setLabel(event.target.value)} />}
          </Field>
          <Field label="Category">
            {({ id }) => (
              <select id={id} className="select" value={category} onChange={(event) => setCategory(event.target.value)}>
                {categories.map((value) => (
                  <option key={value} value={value}>
                    {dataTypeInfo(value).label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Button type="submit" icon="upload" disabled={fileName === "" || label.trim().length < 2} busy={upload.pending} className="align-end">
            Fingerprint
          </Button>
        </form>
        <ActionError error={upload.error} />
        {upload.result &&
          (upload.result.duplicate ? (
            <Notice tone="warning" role="status">
              This document was already fingerprinted as “{upload.result.document.label}”, so nothing was added.
            </Notice>
          ) : (
            <Notice tone="success" role="status">
              “{upload.result.document.label}” was fingerprinted in {plural(upload.result.document.chunks, "chunk")} and its text discarded. A prompt that quotes it is recognised from the next
              request.
            </Notice>
          ))}
      </div>

      <div className="stack stack-sm">
        <div className="row">
          <SourceFilter
            value={source}
            onChange={(value) => {
              setSource(value);
              setOffset(0);
            }}
          />
          <SearchField
            value={search}
            placeholder="Label or category"
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
          />
        </div>
        <ActionError error={change.error} />
        <ResourceView
          resource={documents}
          label="documents"
          isEmpty={(items) => items.length === 0}
          empty={<EmptyState title="No documents in this layer">Fingerprint a document above, or choose another layer.</EmptyState>}
        >
          {(items) => {
            const shown = pageOf(items, search, offset, (document) => `${document.label} ${document.category} ${dataTypeInfo(document.category).label}`);
            if (shown.total === 0) return <EmptyState title="No documents match">Change the search.</EmptyState>;
            return (
              <div className="stack stack-sm">
                <TableWrap>
                  <table className="table table-stack table-fixed">
                    <thead>
                      <tr>
                        <th scope="col">Label</th>
                        <th scope="col" className="col-category">
                          Category
                        </th>
                        <th scope="col" className="col-layer">
                          Layer
                        </th>
                        <th scope="col" className="col-date">
                          Added
                        </th>
                        <th scope="col" className="col-use">
                          Use or remove
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.rows.map((document) => (
                        <tr key={document.id}>
                          <th scope="row" data-label="Label" className="wrap-anywhere" lang={document.language ?? undefined} title={document.label}>
                            {document.label}
                            {document.stale && <span className="cell-detail">Stale: made with another embedder. Upload it again.</span>}
                          </th>
                          <td data-label="Category">
                            <TypeChip type={document.category} />
                          </td>
                          <td data-label="Layer">
                            <SourceBadge source={document.source} />
                          </td>
                          <td data-label="Added">{formatDate(document.created)}</td>
                          <td data-label="Use or remove">
                            <RowControls
                              source={document.source}
                              enabled={document.enabled}
                              name={document.label}
                              busy={change.pending}
                              onToggle={(enabled) => void change.run(document.id, enabled)}
                              onDelete={() => void change.run(document.id, null)}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
                <Pagination offset={shown.start} limit={PAGE_SIZE} total={shown.total} onChange={setOffset} />
              </div>
            );
          }}
        </ResourceView>
      </div>
    </>
  );
}

export function PatternsPanel({ summary, dataTypes, onChanged }: PanelProps & { dataTypes: readonly string[] }) {
  const [name, setName] = useState("");
  const [regex, setRegex] = useState("");
  const [dataType, setDataType] = useState("");
  const [source, setSource] = useState<RowSource | "">("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const patterns = useResource("patterns", (signal) => unwrap(gateway.GET("/api/protected/patterns", { signal })));
  const refresh = () => {
    patterns.reload();
    onChanged();
  };
  const add = useAction(async () => {
    const created = await unwrap(gateway.POST("/api/protected/patterns", { body: { name: name.trim(), regex, data_type: dataType.trim().toUpperCase() } }));
    setName("");
    setRegex("");
    refresh();
    return created;
  });
  const change = useAction(async (id: string, enabled: boolean | null) => {
    if (enabled === null) await unwrap(gateway.DELETE("/api/protected/patterns/{pattern_id}", { params: { path: { pattern_id: id } } }));
    else await unwrap(gateway.PATCH("/api/protected/patterns/{pattern_id}", { params: { path: { pattern_id: id } }, body: { enabled } }));
    refresh();
  });
  const ready = name.trim().length >= 2 && regex !== "" && dataType.trim() !== "";

  function onAdd(event: FormEvent) {
    event.preventDefault();
    if (ready) void add.run();
  }

  return (
    <>
      <DefaultGroups store="patterns" groups={summary.groups} onChanged={refresh} />
      <PatternAssist onAdded={refresh} />

      <div className="stack stack-sm">
        <h3>Add a custom pattern</h3>
        <form className="row" onSubmit={onAdd}>
          <Field label="Name">
            {({ id }) => <input id={id} className="input" value={name} maxLength={120} placeholder="Ticket number" onChange={(event) => setName(event.target.value)} />}
          </Field>
          <Field label="Regular expression">
            {({ id }) => <input id={id} className="input mono" value={regex} maxLength={2000} spellCheck={false} placeholder={String.raw`\bTCK-\d{6}\b`} onChange={(event) => setRegex(event.target.value)} />}
          </Field>
          <Field label="Data type">
            {({ id, describedBy }) => (
              <>
                <input id={id} className="input" value={dataType} list={`${id}-types`} aria-describedby={describedBy} placeholder="TICKET" onChange={(event) => setDataType(event.target.value)} />
                <datalist id={`${id}-types`}>
                  {dataTypes.map((type) => (
                    <option key={type} value={type}>
                      {dataTypeInfo(type).label}
                    </option>
                  ))}
                </datalist>
              </>
            )}
          </Field>
          <Button type="submit" icon="plus" disabled={!ready} busy={add.pending} className="align-end">
            Add pattern
          </Button>
        </form>
        <ActionError error={add.error} />
        {add.result && (
          <Notice tone="success" role="status">
            “{add.result.name}” was added. Detection uses it from the next request.
          </Notice>
        )}
      </div>

      <div className="stack stack-sm">
        <div className="row">
          <SourceFilter
            value={source}
            onChange={(value) => {
              setSource(value);
              setOffset(0);
            }}
          />
          <SearchField
            value={search}
            placeholder="Name, expression or data type"
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
          />
        </div>
        <ActionError error={change.error} />
        <ResourceView resource={patterns} label="patterns" isEmpty={(items) => items.length === 0} empty={<EmptyState title="No patterns">Add one above.</EmptyState>}>
          {(items) => {
            const inLayer = source ? items.filter((pattern) => pattern.source === source) : items;
            const shown = pageOf(inLayer, search, offset, (pattern) => `${pattern.name} ${pattern.regex} ${pattern.data_type} ${dataTypeInfo(pattern.data_type).label}`);
            if (shown.total === 0) return <EmptyState title="No patterns match">Change the filter or the search.</EmptyState>;
            return (
              <div className="stack stack-sm">
                <TableWrap>
                  <table className="table table-stack table-fixed">
                    <thead>
                      <tr>
                        <th scope="col" className="col-name">
                          Name
                        </th>
                        <th scope="col">Regular expression</th>
                        <th scope="col" className="col-type">
                          Data type
                        </th>
                        <th scope="col" className="col-layer">
                          Layer
                        </th>
                        <th scope="col" className="col-use">
                          Use or remove
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.rows.map((pattern) => (
                        <tr key={pattern.id}>
                          <th scope="row" data-label="Name" title={pattern.name}>
                            {pattern.name}
                          </th>
                          <td data-label="Regular expression" title={pattern.regex}>
                            <code className="wrap-anywhere">{pattern.regex}</code>
                          </td>
                          <td data-label="Data type">
                            <TypeChip type={pattern.data_type} />
                          </td>
                          <td data-label="Layer">
                            <SourceBadge source={pattern.source} />
                          </td>
                          <td data-label="Use or remove">
                            <RowControls
                              source={pattern.source}
                              enabled={pattern.enabled}
                              name={pattern.name}
                              busy={change.pending}
                              onToggle={(enabled) => void change.run(pattern.id, enabled)}
                              onDelete={() => void change.run(pattern.id, null)}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
                <Pagination offset={shown.start} limit={PAGE_SIZE} total={shown.total} onChange={setOffset} />
              </div>
            );
          }}
        </ResourceView>
      </div>
    </>
  );
}
