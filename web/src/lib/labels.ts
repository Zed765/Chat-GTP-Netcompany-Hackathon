import type { Action, Channel, InjectionProtection, Role, RowSource, Store, Tier, ToolStatus } from "../api/types";
import type { IconName } from "../ui/Icon";
import type { Hue } from "./dataTypes";

interface Look {
  label: string;
  hue: Hue;
  icon: IconName;
}

export const ACTIONS: Record<Action, Look & { past: string; meaning: string }> = {
  allow: {
    label: "Allow",
    past: "Sent as written",
    meaning: "Nothing sensitive was found, so the text went out unchanged.",
    hue: "green",
    icon: "check",
  },
  redact: {
    label: "Redact",
    past: "Masked and sent",
    meaning: "Sensitive values were swapped for placeholders before sending, and restored in the answer.",
    hue: "blue",
    icon: "mask",
  },
  warn: {
    label: "Warn",
    past: "Warning",
    meaning: "The sender is shown what was found and chooses to send the masked version or cancel.",
    hue: "yellow",
    icon: "alert",
  },
  block: {
    label: "Block",
    past: "Blocked",
    meaning: "Nothing was sent to the AI tool.",
    hue: "red",
    icon: "block",
  },
};

export const ACTION_ORDER: readonly Action[] = ["allow", "redact", "warn", "block"];

export const TOOL_STATUS: Record<ToolStatus, Look> = {
  approved: { label: "Approved", hue: "green", icon: "shield-check" },
  tolerated: { label: "Tolerated", hue: "yellow", icon: "info" },
  unapproved: { label: "Unapproved", hue: "red", icon: "block" },
  unknown: { label: "Unknown", hue: "neutral", icon: "search" },
};

export const TIERS: Record<Tier, { label: string; detail: string }> = {
  T0: { label: "Patterns", detail: "Patterns with checksum validation, run locally" },
  T1: { label: "Names and terms", detail: "Name recognition and the protected terms list, run locally" },
  T2: { label: "Fingerprints", detail: "Similarity to protected documents, on masked text" },
  T3: { label: "Model", detail: "Classification by the language model, on masked text" },
};

export const SOURCES: Record<RowSource, string> = {
  default: "Default pack",
  synced: "Synced from CRM",
  uploaded: "Uploaded",
  seeded: "Demo organisation",
};

export const STORES: Record<Store, { label: string; tier: Tier; unit: string }> = {
  terms: { label: "Protected terms", tier: "T1", unit: "term" },
  fingerprints: { label: "Document fingerprints", tier: "T2", unit: "document" },
  patterns: { label: "Custom patterns", tier: "T0", unit: "pattern" },
};

export const ROLES: Record<Role, string> = {
  employee: "Employee",
  admin: "Admin",
  service: "Service",
};

export const PROTECTION: Record<InjectionProtection, { label: string; detail: string }> = {
  off: {
    label: "Off",
    detail: "No injection checks and no taint tracking. The vault is the only defence: tools outside the company still receive placeholders only.",
  },
  standard: {
    label: "Standard",
    detail: "Heuristics and the canary check every tool result. The model confirms only what the heuristics flag.",
  },
  detailed: {
    label: "Detailed",
    detail: "As standard, and the model also checks all content from untrusted sources. One extra model call per untrusted result.",
  },
};

/** The systems the agent reaches, by the name the gateway knows them under. */
export const AGENT_SYSTEMS: Record<string, string> = {
  crm: "CRM",
  mail: "Mail",
  web: "Web",
};

export const CHANNELS: Record<Channel, string> = {
  prompt: "Prompt",
  tool_call: "Agent tool call",
  tool_result: "Agent tool result",
};
