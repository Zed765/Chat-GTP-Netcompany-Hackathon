import { useCallback, useEffect, useRef, useState } from "react";
import { type ApiError, isAbort, toApiError } from "../api/errors";

export type Resource<T> = (
  | { status: "loading"; data: undefined; error: undefined }
  | { status: "ready"; data: T; error: undefined }
  | { status: "error"; data: undefined; error: ApiError }
) & {
  /** True while newer data is on its way and the previous data is still shown. */
  refreshing: boolean;
  reload: () => void;
  /** Replace the data locally, for example with the response of a write. */
  setData: (data: T) => void;
};

/** The outcome of one request, tagged with the request it answers. */
type Settled<T> = { request: string } & ({ data: T; error: undefined } | { data: undefined; error: ApiError });

interface Options {
  /** Reload quietly at this interval, for views that show live data. */
  pollMs?: number;
}

/**
 * Loads data for a view and tracks its loading, ready and error states.
 * The request runs again when `key` changes; the previous data stays visible meanwhile.
 */
export function useResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
  { pollMs }: Options = {},
): Resource<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);
  const request = `${key}#${attempt}`;

  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    const controller = new AbortController();
    loadRef
      .current(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setSettled({ request, data, error: undefined });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || isAbort(error)) return;
        setSettled({ request, data: undefined, error: toApiError(error) });
      });
    return () => controller.abort();
  }, [request]);

  useEffect(() => {
    if (!pollMs) return undefined;
    const controller = new AbortController();
    const timer = setInterval(() => {
      loadRef
        .current(controller.signal)
        .then((data) => {
          if (!controller.signal.aborted) setSettled({ request, data, error: undefined });
        })
        // A failed poll keeps the data already on screen; the next one tries again.
        .catch(() => undefined);
    }, pollMs);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [pollMs, request]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  const setData = useCallback((data: T) => setSettled({ request, data, error: undefined }), [request]);

  const pending = settled?.request !== request;
  if (settled === null || (settled.error && pending)) {
    return { status: "loading", data: undefined, error: undefined, refreshing: false, reload, setData };
  }
  if (settled.error) return { status: "error", data: undefined, error: settled.error, refreshing: false, reload, setData };
  return { status: "ready", data: settled.data, error: undefined, refreshing: pending, reload, setData };
}
