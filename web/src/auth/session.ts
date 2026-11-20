import type { Session } from "../api/types";

const STORAGE_KEY = "aspida.session";

function readStored(): Session | null {
  try {
    const raw = globalThis.sessionStorage?.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function writeStored(session: Session | null): void {
  try {
    if (session) globalThis.sessionStorage?.setItem(STORAGE_KEY, JSON.stringify(session));
    else globalThis.sessionStorage?.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode); the session then lasts until reload.
  }
}

let current: Session | null = readStored();
let refreshing: Promise<string | null> | null = null;
const listeners = new Set<() => void>();

async function login(userId: string): Promise<Session | null> {
  const response = await fetch("/api/demo/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId }),
  });
  return response.ok ? ((await response.json()) as Session) : null;
}

/** The demo session: who is signed in and the bearer token for every request. */
export const sessionStore = {
  get: (): Session | null => current,

  set(session: Session | null): void {
    current = session;
    writeStored(session);
    for (const listener of listeners) listener();
  },

  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },

  /** Signs the same demo user in again after a 401; concurrent callers share one attempt. */
  refresh(): Promise<string | null> {
    const user = current?.user;
    if (!user) return Promise.resolve(null);
    refreshing ??= login(user.user_id)
      .then((session) => {
        sessionStore.set(session);
        return session?.token ?? null;
      })
      .catch(() => null)
      .finally(() => {
        refreshing = null;
      });
    return refreshing;
  },
};
