import { type ComponentType, type LazyExoticComponent, lazy } from "react";
import type { IconName } from "./ui/Icon";

/** The roles a visitor can take. The gateway also has a `service` role, which never signs in here. */
export type DemoRole = "employee" | "admin";

export interface Page {
  path: string;
  title: string;
  icon: IconName;
  /** Who may open the page. This mirrors what the gateway authorises; the gateway enforces it. */
  roles: readonly DemoRole[];
  component: LazyExoticComponent<ComponentType>;
}

const EVERYONE: readonly DemoRole[] = ["employee", "admin"];

/** Each page is its own chunk, so a visitor downloads only the pages they open. */
export const PAGES: readonly Page[] = [
  { path: "/chat", title: "Chat", icon: "chat", roles: EVERYONE, component: lazy(() => import("./pages/ChatPage")) },
  { path: "/agent", title: "Agent", icon: "bot", roles: EVERYONE, component: lazy(() => import("./pages/AgentPage")) },
  { path: "/overview", title: "Monitor", icon: "chart", roles: ["admin"], component: lazy(() => import("./pages/OverviewPage")) },
  { path: "/configure", title: "Configure", icon: "policy", roles: ["admin"], component: lazy(() => import("./pages/ConfigurePage")) },
  { path: "/sent-emails", title: "Sent emails", icon: "send", roles: EVERYONE, component: lazy(() => import("./pages/SentEmailsPage")) },
];

export const HOME: Record<DemoRole, string> = {
  employee: "/chat",
  admin: "/overview",
};

export function isDemoRole(role: string): role is DemoRole {
  return role === "employee" || role === "admin";
}

export function pagesFor(role: string): Page[] {
  return PAGES.filter((page) => isDemoRole(role) && page.roles.includes(role));
}
