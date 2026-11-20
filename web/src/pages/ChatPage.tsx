import { type FormEvent, type KeyboardEvent, useEffect, useId, useReducer, useRef, useState } from "react";
import { gateway, unwrap } from "../api/client";
import type { ToolOut } from "../api/types";
import { useAuth } from "../auth/context";
import { type Turn, historyBefore, sendTurn, turnsReducer } from "../features/chat/turns";
import { Greeting } from "../features/chat/Greeting";
import { type Side, TurnView } from "../features/chat/TurnView";
import { maskedByTurn } from "../features/chat/vault";
import "../features/chat/chat.css";
import { useResource } from "../hooks/useResource";
import { ACTIONS } from "../lib/labels";
import { textLang } from "../lib/lang";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Segmented } from "../ui/controls";
import { Icon } from "../ui/Icon";
import { PageHeader } from "../ui/PageHeader";
import { EmptyState, ResourceView } from "../ui/States";

const newId = () => crypto.randomUUID();

interface ToolMenuProps {
  tools: ToolOut[];
  selected: string;
  onSelect: (slug: string) => void;
}

/** The colour of the dot beside a tool: its status. */
const STATUS_HUE: Partial<Record<ToolOut["status"], string>> = { approved: "green", tolerated: "yellow", unapproved: "red" };

const menuItems = (root: HTMLElement | null) => [...(root?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? [])];

/** The AI tool the message goes to: a button in the message box that opens the list of tools. */
function ToolMenu({ tools, selected, onSelect }: ToolMenuProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const current = tools.find((tool) => tool.slug === selected);

  useEffect(() => {
    if (!open) return;
    const items = menuItems(root.current);
    (items.find((item) => item.getAttribute("aria-checked") === "true") ?? items[0])?.focus();
    const closeOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);

  function close() {
    setOpen(false);
    button.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLUListElement>) {
    if (event.key === "Escape") return close();
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const all = menuItems(root.current);
    const at = all.indexOf(document.activeElement as HTMLButtonElement);
    all[(at + (event.key === "ArrowDown" ? 1 : all.length - 1)) % all.length]?.focus();
  }

  return (
    <div className="tool-menu" ref={root}>
      <button type="button" ref={button} className="tool-menu-button" aria-haspopup="menu" aria-expanded={open} aria-controls={menuId} onClick={() => setOpen((value) => !value)}>
        <span className="tool-dot" data-hue={current && STATUS_HUE[current.status]} />
        {current?.name ?? "Choose an AI tool"}
        <Icon name="chevron-down" size={14} />
      </button>
      {open && (
        <ul id={menuId} className="tool-menu-list" role="menu" aria-label="AI tool" onKeyDown={onKeyDown}>
          {tools.map((tool) => (
            <li key={tool.slug} role="none">
              <button
                type="button"
                role="menuitemradio"
                aria-checked={tool.slug === selected}
                className="tool-menu-item"
                onClick={() => {
                  onSelect(tool.slug);
                  close();
                }}
              >
                <span className="tool-dot" data-hue={STATUS_HUE[tool.status]} />
                <span className="grow">{tool.name}</span>
                {tool.slug === selected && <Icon name="check" size={14} />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ChatPage() {
  const tools = useResource("demo-tools", (signal) => unwrap(gateway.GET("/api/tools", { params: { query: { demo_only: true } }, signal })));
  const [turns, dispatch] = useReducer(turnsReducer, []);
  const [conversationId, setConversationId] = useState(newId);
  const { user } = useAuth();
  const [chosen, setChosen] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [side, setSide] = useState<Side>("you");
  const composer = useRef<HTMLTextAreaElement>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);

  const latestId = turns.at(-1)?.id;
  useEffect(() => {
    if (latestId) document.getElementById(`turn-${latestId}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [latestId]);

  const available = tools.data ?? [];
  const selected = available.find((tool) => tool.slug === chosen) ?? available.find((tool) => tool.status === "unapproved") ?? available[0];
  const latest = turns.at(-1);

  async function send(id: string, tool: Turn["tool"], prompt: string, acknowledge?: string) {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setBusy(true);
    await sendTurn(gateway, dispatch, { id, tool, prompt, conversationId, history: historyBefore(turns, id), acknowledge, signal: controller.signal });
    if (inFlight.current === controller) setBusy(false);
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const prompt = draft.trim();
    if (!prompt || !selected || busy) return;
    setDraft("");
    void send(newId(), { slug: selected.slug, name: selected.name }, prompt);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift + Enter starts a new line. Enter that confirms an input-method choice does neither.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  function startOver() {
    inFlight.current?.abort();
    setBusy(false);
    // Ends the conversation's vault entries now instead of leaving them to expire.
    void gateway.POST("/api/conversations/{conversation_id}/end", { params: { path: { conversation_id: conversationId } } }).catch(() => undefined);
    dispatch({ type: "cleared" });
    setSide("you");
    setConversationId(newId());
    composer.current?.focus();
  }

  const status = latest?.trace ? `${ACTIONS[latest.trace.action].past}. ${latest.trace.explanation.summary}` : "";
  const started = turns.length > 0;

  // The message box moves into the conversation with the first message; typing carries on there.
  useEffect(() => {
    if (started) composer.current?.focus();
  }, [started]);

  const known = maskedByTurn(turns);
  const masked = (known.at(-1) ?? []).length > 0;
  // The switch names the tool when the conversation used one, as it usually does.
  const toolNames = new Set(turns.map((turn) => turn.tool.name));
  const toolName = toolNames.size === 1 ? [...toolNames][0] : "AI tool";

  const messageBox = (items: ToolOut[]) => (
    <form className="composer" onSubmit={onSubmit}>
      <textarea
        ref={composer}
        className="composer-input"
        rows={1}
        aria-label="Your message"
        value={draft}
        lang={textLang(draft)}
        placeholder="Type a message. Enter to send, Shift + Enter for a new line"
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <div className="composer-bar">
        <ToolMenu tools={items} selected={selected?.slug ?? ""} onSelect={setChosen} />
        {started && (
          <span className="row">
            {/* One switch for the whole conversation, where it is always in view: as you see it, or as the AI tool does. */}
            {masked && (
              <Segmented
                legend="Whose view of the conversation"
                hideLegend
                options={[
                  { value: "you", label: "You" },
                  { value: "tool", label: toolName },
                ]}
                value={side}
                onChange={setSide}
              />
            )}
            <Button variant="ghost" size="sm" icon="plus" onClick={startOver}>
              New conversation
            </Button>
          </span>
        )}
      </div>
    </form>
  );

  return (
    <div className="page">
      <PageHeader title="Chat" hideTitle />

      <ResourceView
        resource={tools}
        label="AI tools"
        isEmpty={(items) => items.length === 0}
        empty={
          <EmptyState icon="chat" title="No AI tools to chat with">
            The inventory has no demo tools yet. They are added when the gateway starts with demo data.
          </EmptyState>
        }
      >
        {(items) =>
          started ? (
            <Card>
              <div role="log" aria-label="Conversation">
                <ol className="messages">
                  {turns.map((turn, index) => (
                    <TurnView
                      key={turn.id}
                      turn={turn}
                      known={known[index] ?? []}
                      side={side}
                      busy={busy}
                      onAcknowledge={() => void send(turn.id, turn.tool, turn.prompt, turn.trace?.trace_id)}
                      onCancel={() => dispatch({ type: "cancelled", id: turn.id })}
                      onRetry={() => void send(turn.id, turn.tool, turn.prompt)}
                    />
                  ))}
                </ol>
              </div>
              {messageBox(items)}
            </Card>
          ) : (
            <div className="chat-empty">
              <Greeting name={user.display_name.split(" ")[0] ?? user.display_name} />
              {messageBox(items)}
            </div>
          )
        }
      </ResourceView>

      <p className="sr-only" role="status">
        {status}
      </p>
    </div>
  );
}
