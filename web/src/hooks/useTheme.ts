import { useCallback, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "aspida.theme";
const listeners = new Set<() => void>();
const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)");

function readStored(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

/** The user's explicit choice; `null` follows the system setting. */
let choice: Theme | null = null;

function current(): Theme {
  return choice ?? (systemDark().matches ? "dark" : "light");
}

function apply(): void {
  if (choice) document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
}

/** Call before the first render so the stored choice is in place without a flash. */
export function restoreTheme(): void {
  choice = readStored();
  apply();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const media = systemDark();
  media.addEventListener("change", listener);
  return () => {
    listeners.delete(listener);
    media.removeEventListener("change", listener);
  };
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const theme = useSyncExternalStore(subscribe, current);
  const toggle = useCallback(() => {
    choice = current() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(STORAGE_KEY, choice);
    } catch {
      // Without storage the choice lasts until the page is reloaded.
    }
    apply();
    for (const listener of listeners) listener();
  }, []);
  return { theme, toggle };
}
