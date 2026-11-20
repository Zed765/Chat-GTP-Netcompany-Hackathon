import { createContext, useContext } from "react";
import type { Principal } from "../api/types";

export interface Auth {
  user: Principal;
  /** The demo users a visitor can become. */
  users: readonly Principal[];
  signIn: (userId: string) => Promise<void>;
  /** The user id being signed in, while a switch is in flight. */
  switchingTo: string | null;
}

export const AuthContext = createContext<Auth | null>(null);

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth must be used inside AuthProvider");
  return auth;
}
