import { type FormEvent, Fragment, type KeyboardEvent, useCallback, useEffect, useReducer, useRef, useState } from "react";
import { agent, gateway, unwrap } from "../api/client";
import { apiError, isAbort, toApiError } from "../api/errors";
import type { AgentSession } from "../api/types";
import { useAuth } from "../auth/context";
import { ActivityRow } from "../features/agent/ActivityRow";
import { Greeting } from "../features/chat/Greeting";
import "../features/agent/agent.css";
import "../features/chat/chat.css";
import { INITIAL_AGENT_STATE, activitiesByRequest, agentEvents, agentReducer, isAwaitingConfirmation } from "../features/agent/session";
import { textLang } from "../lib/lang";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Markdown } from "../ui/Markdown";
import { Notice } from "../ui/Notice";
import { PageHeader } from "../ui/PageHeader";
import { PlaceholderText } from "../ui/SensitiveText";
import { ErrorState, Loading } from "../ui/States";
import { Segmented } from "../ui/controls";

const placeholders = (text: string) => <PlaceholderText text={text} />;

/** Whose side of the firewall the conversation is shown from: yours, or the agent's model's. */
type Side = "you" | "agent";

const sessionKey = (userId: string) => `aspida.agent-session.${userId}`;

async function openSession(userId: string, signal: AbortSignal): Promise<AgentSession> {
  const stored = sessionStorage.getItem(sessionKey(userId));
  if (stored) {
    const existing = await agent.GET("/sessions/{session_id}", { params: { path: { session_id: stored } }, signal });
    if (existing.data) return existing.data;
  }
  const created = await unwrap(agent.POST("/sessions", { signal }));
  sessionStorage.setItem(sessionKey(userId), created.session_id);
  return created;
}

export default function AgentPage() {
  const { user } = useAuth();
  const [state, dispatch] = useReducer(agentReducer, INITIAL_AGENT_STATE);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [side, setSide] = useState<Side>("you");
  // The finished messages as the agent's model saw them, in the order of the conversation.
  const [seen, setSeen] = useState<string[] | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const inFlight = useRef<AbortController | null>(null);

  const connect = useCallback(
    (signal: AbortSignal) =>
      openSession(user.user_id, signal)
        .then((session) => dispatch({ type: "loaded", session }))
        .catch((error: unknown) => {
          if (!isAbort(error)) setSessionError(toApiError(error).message);
        }),
    [user.user_id],
  );

  useEffect(() => {
    const controller = new AbortController();
    void connect(controller.signal);
    return () => controller.abort();
  }, [connect]);

  useEffect(() => () => inFlight.current?.abort(), []);

  // When a turn ends, ask how the conversation read on the model's side. The gateway swaps the
  // values this session's vault holds for their placeholders, and sends back nothing else.
  const { sessionId: session, messages: finished, running: busy } = state;
  useEffect(() => {
    if (!session || busy || finished.length === 0) return undefined;
    const controller = new AbortController();
    unwrap(
      gateway.POST("/api/agent/sessions/{session_id}/as-seen", {
        params: { path: { session_id: session } },
        body: { texts: finished.map((message) => message.content) },
        signal: controller.signal,
      }),
    )
      .then(({ texts }) => setSeen(texts))
      // Without an answer the conversation keeps the one view it has.
      .catch(() => undefined);
    return () => controller.abort();
  }, [session, finished, busy]);

  /** Plays one event stream (a new message, or the continuation after a confirmation) into the state. */
  const play = useCallback(async (start: (signal: AbortSignal) => Promise<{ data?: ReadableStream<Uint8Array> | null; error?: unknown; response: Response }>) => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    try {
      const { data, error, response } = await start(controller.signal);
      if (!response.ok || !data) throw apiError(response.status, error);
      for await (const event of agentEvents(data)) dispatch({ type: "event", event });
      dispatch({ type: "ended" });
    } catch (error) {
      if (!isAbort(error)) dispatch({ type: "failed", message: toApiError(error).message });
    }
  }, []);

  function ask(content: string) {
    const sessionId = state.sessionId;
    if (!sessionId || state.running) return;
    dispatch({ type: "asked", content });
    void play((signal) => agent.POST("/sessions/{session_id}/messages", { params: { path: { session_id: sessionId } }, body: { content }, parseAs: "stream", signal }));
  }

  function confirm(callId: string, approve: boolean) {
    const sessionId = state.sessionId;
    if (!sessionId) return;
    dispatch({ type: "decided", callId, approve });
    void play((signal) =>
      agent.POST("/sessions/{session_id}/confirmations/{call_id}", { params: { path: { session_id: sessionId, call_id: callId } }, body: { approve }, parseAs: "stream", signal }),
    );
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || state.running) return;
    setDraft("");
    ask(content);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift + Enter starts a new line. Enter that confirms an input-method choice does neither.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  function startOver() {
    inFlight.current?.abort();
    // Ends the old session's vault entries now; a session that is already gone is fine.
    if (state.sessionId) void agent.DELETE("/sessions/{session_id}", { params: { path: { session_id: state.sessionId } } }).catch(() => undefined);
    sessionStorage.removeItem(sessionKey(user.user_id));
    setSessionError(null);
    setSide("you");
    setSeen(null);
    dispatch({ type: "closed" });
    void connect(new AbortController().signal);
  }

  const started = state.messages.length > 0 || state.running || state.trace.length > 0;
  const activities = activitiesByRequest(state);
  // Each message with the number of the request it is, when it is one.
  const requests = state.messages.map((message, index) => ({
    message,
    request: message.role === "user" ? state.messages.slice(0, index).filter((earlier) => earlier.role === "user").length : null,
  }));

  // The switch is offered once something in the conversation reads differently on the agent's side.
  const masked = seen !== null && state.messages.some((message, index) => seen[index] !== undefined && seen[index] !== message.content);
  const shown = (index: number, content: string) => (side === "agent" ? (seen?.[index] ?? content) : content);

  // The message box moves into the conversation with the first request; typing carries on there.
  useEffect(() => {
    if (started) composer.current?.focus();
  }, [started]);

  const messageBox = (
    <form className="composer" onSubmit={onSubmit}>
      <textarea
        ref={composer}
        className="composer-input"
        rows={1}
        aria-label="Your request"
        value={draft}
        lang={textLang(draft)}
        placeholder="Ask the agent. Enter to send, Shift + Enter for a new line"
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
      />
      {started && (
        <div className="composer-bar composer-bar-end">
          {/* One switch for the whole conversation, as on Chat: as you see it, or as the agent's model does. */}
          {masked && (
            <Segmented
              legend="Whose view of the conversation"
              hideLegend
              options={[
                { value: "you", label: "You" },
                { value: "agent", label: "Agent" },
              ]}
              value={side}
              onChange={setSide}
            />
          )}
          <Button variant="ghost" size="sm" icon="plus" onClick={startOver}>
            New session
          </Button>
        </div>
      )}
    </form>
  );

  return (
    <div className="page">
      <PageHeader title="Agent" hideTitle />

      {sessionError ? (
        <ErrorState title="The agent cannot be reached" message={sessionError} onRetry={startOver} />
      ) : !state.sessionId ? (
        <Loading label="Starting an agent session" />
      ) : !started ? (
        <div className="chat-empty">
          <Greeting name={user.display_name.split(" ")[0] ?? user.display_name} />
          <p className="greeting-note">The agent can look up clients in the CRM, read web pages and the helpdesk inbox, and send email.</p>
          {messageBox}
        </div>
      ) : (
        <div className="agent-chat">
          {state.tainted && (
            <Notice tone="warning" title="Session tainted" role="status">
              The agent read content from an untrusted source{state.taintSource ? ` (${state.taintSource})` : ""}, so its tool calls with side effects are now blocked.
            </Notice>
          )}

          <Card>
            {started && (
              <div role="log" aria-label="Conversation with the agent">
                <ol className="messages">
                  {requests.map(({ message, request }, index) => (
                    <Fragment key={index}>
                      <li className={`message message-${message.role}`} lang={textLang(message.content)}>
                        {/* Keyed by side, so the swapped values draw themselves in again when the view flips. */}
                        <div key={side} className="swap">
                          {message.role === "user" ? <PlaceholderText text={shown(index, message.content)} /> : <Markdown text={shown(index, message.content)} leaf={placeholders} />}
                        </div>
                      </li>
                      {request !== null && activities.has(request) && (
                        <li>
                          <ul className="activities" aria-label="What the agent did">
                            {(activities.get(request) ?? []).map((activity) => (
                              <ActivityRow
                                key={activity.callId}
                                activity={activity}
                                decided={state.decisions[activity.callId]}
                                awaiting={activity.call !== null && isAwaitingConfirmation(state, activity.call)}
                                busy={state.running}
                                onConfirm={(approve) => confirm(activity.callId, approve)}
                              />
                            ))}
                          </ul>
                        </li>
                      )}
                    </Fragment>
                  ))}
                  {state.running && (
                    <li className="message message-assistant" lang={textLang(state.reply)}>
                      {state.reply ? <Markdown text={state.reply} leaf={placeholders} /> : <span className="muted">Working</span>}
                      <span className="caret" aria-hidden="true" />
                    </li>
                  )}
                </ol>
              </div>
            )}
            {state.error && (
              <Notice tone="danger" title="The agent stopped" role="alert">
                {state.error}
              </Notice>
            )}
            {messageBox}
          </Card>
        </div>
      )}
    </div>
  );
}
