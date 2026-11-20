import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { gateway, unwrap } from "../api/client";
import { toApiError } from "../api/errors";
import { useResource } from "../hooks/useResource";
import { ErrorState, Loading } from "../ui/States";
import { type Auth, AuthContext } from "./context";
import { sessionStore } from "./session";

const login = (userId: string) => unwrap(gateway.POST("/api/demo/login", { body: { user_id: userId } }));

/**
 * Demo sign-in: loads the demo users and keeps the session. There is no sign-in page: a
 * first visit starts as the employee, and a session that has ended starts again by itself
 * under the role it had.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const session = useSyncExternalStore(sessionStore.subscribe, sessionStore.get);
  const [switchingTo, setSwitchingTo] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const users = useResource("demo-users", async (signal) => {
    const found = await unwrap(gateway.GET("/api/demo/users", { signal }));
    const first = found.find((user) => user.role === "employee") ?? found[0];
    if (!sessionStore.get() && first) sessionStore.set(await login(first.user_id));
    return found;
  });

  const signIn = useCallback(async (userId: string) => {
    setSwitchingTo(userId);
    setFailure(null);
    try {
      sessionStore.set(await login(userId));
    } catch (error) {
      setFailure(toApiError(error).message);
    } finally {
      setSwitchingTo(null);
    }
  }, []);

  const lastUserId = useRef<string | null>(null);
  useEffect(() => {
    if (session) lastUserId.current = session.user.user_id;
  }, [session]);
  const ended = !session && users.data !== undefined && switchingTo === null && failure === null;
  useEffect(() => {
    if (!ended) return;
    const again = users.data?.find((user) => user.user_id === lastUserId.current) ?? users.data?.find((user) => user.role === "employee") ?? users.data?.[0];
    if (again) void signIn(again.user_id);
  }, [ended, users.data, signIn]);

  const auth = useMemo<Auth | null>(
    () => (session && users.data ? { user: session.user, users: users.data, signIn, switchingTo } : null),
    [session, users.data, signIn, switchingTo],
  );

  if (users.status === "error" || failure) {
    return (
      <ErrorState
        title="The gateway cannot be reached"
        message={users.error?.message ?? failure ?? ""}
        onRetry={() => {
          setFailure(null);
          users.reload();
        }}
      />
    );
  }
  if (!auth) return <Loading label="Signing in to the demo" />;
  return <AuthContext value={auth}>{children}</AuthContext>;
}
