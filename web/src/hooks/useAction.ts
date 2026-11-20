import { useCallback, useEffect, useRef, useState } from "react";
import { type ApiError, toApiError } from "../api/errors";

export interface ActionState<Args extends unknown[], Result> {
  /** Runs the action; resolves to its result, or to `undefined` if it failed. */
  run: (...args: Args) => Promise<Result | undefined>;
  pending: boolean;
  error: ApiError | null;
  result: Result | undefined;
  reset: () => void;
}

/** Tracks one write (a save, an upload, a decision): pending, the last result, the last error. */
export function useAction<Args extends unknown[], Result>(
  action: (...args: Args) => Promise<Result>,
): ActionState<Args, Result> {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<Result | undefined>(undefined);
  const actionRef = useRef(action);
  const mounted = useRef(true);

  useEffect(() => {
    actionRef.current = action;
  });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(async (...args: Args): Promise<Result | undefined> => {
    setPending(true);
    setError(null);
    try {
      const value = await actionRef.current(...args);
      if (mounted.current) setResult(value);
      return value;
    } catch (caught) {
      if (mounted.current) setError(toApiError(caught));
      return undefined;
    } finally {
      if (mounted.current) setPending(false);
    }
  }, []);

  const reset = useCallback(() => {
    setError(null);
    setResult(undefined);
  }, []);

  return { run, pending, error, result, reset };
}
