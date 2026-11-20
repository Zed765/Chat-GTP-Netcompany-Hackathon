import type { Action, DraftResult, ToolStatus, ValidationIssue } from "../api/types";

/** The repository's `policies/default.yaml`, so the editor opens on the real document. */
export const DEFAULT_POLICY_YAML = `# Default policy. Rules are checked in order and the first match wins.
# A rule matches when every key under \`when\` matches; a list matches any of its values.
version: 1

# What to do when a detector fails or times out, by tool status.
#   block       refuse the request
#   mask_local  carry on with what the local tiers (T0 and T1) found
on_error:
  approved: mask_local
  tolerated: block
  unapproved: block
  unknown: block

# off | standard | detailed. See docs/architecture.md, "Injection protection".
injection_protection: standard

rules:
  - name: secrets-never-leave
    when: { data: [SECRET] }
    action: block

  - name: tainted-agent-side-effects
    when: { channel: tool_call, side_effects: true, tainted: true }
    action: block

  - name: untrusted-destinations-get-placeholders
    when: { channel: tool_call, destination: untrusted }
    action: redact

  - name: agent-model-sees-placeholders
    when:
      channel: tool_result
      data: [PERSON, EMAIL, PHONE, AFM, AMKA, IBAN, CARD, ID_CARD, ADDRESS, CLIENT]
    action: redact

  - name: contract-to-unapproved
    when:
      channel: prompt
      tool_status: [unapproved, unknown]
      data: [CONTRACT]
    action: block
    suggest: approved_alternative

  - name: pii-and-client-data
    when:
      channel: prompt
      tool_status: [tolerated, unapproved, unknown]
      data: [PERSON, EMAIL, PHONE, AFM, AMKA, IBAN, CARD, ID_CARD, ADDRESS, CLIENT]
    action: redact

  - name: marked-or-sensitive-category
    when:
      channel: prompt
      tool_status: [tolerated, unapproved, unknown]
      data: [CONFIDENTIAL_MARKER, FINANCIAL, HEALTH, HR, CLIENT_CONFIDENTIAL]
    action: warn

  - name: source-code-warning
    when:
      channel: prompt
      tool_status: [tolerated, unapproved]
      data: [SOURCE_CODE]
    action: warn

  - name: default
    action: allow
`;

const PII = ["PERSON", "EMAIL", "PHONE", "AFM", "AMKA", "IBAN", "CARD", "ID_CARD", "ADDRESS", "CLIENT"];
const SENSITIVE = ["CONFIDENTIAL_MARKER", "FINANCIAL", "HEALTH", "HR", "CLIENT_CONFIDENTIAL"];

export interface Decision {
  action: Action;
  rule: string;
}

/** The default policy's prompt rules, hard-coded: the mock does not interpret the YAML. */
export function decidePrompt(status: ToolStatus, dataTypes: ReadonlySet<string>): Decision {
  const has = (types: readonly string[]) => types.some((type) => dataTypes.has(type));
  const notApproved = status !== "approved";
  if (dataTypes.has("SECRET")) return { action: "block", rule: "secrets-never-leave" };
  if (dataTypes.has("CONTRACT") && (status === "unapproved" || status === "unknown")) {
    return { action: "block", rule: "contract-to-unapproved" };
  }
  if (notApproved && has(PII)) return { action: "redact", rule: "pii-and-client-data" };
  if (notApproved && has(SENSITIVE)) return { action: "warn", rule: "marked-or-sensitive-category" };
  if ((status === "tolerated" || status === "unapproved") && dataTypes.has("SOURCE_CODE")) {
    return { action: "warn", rule: "source-code-warning" };
  }
  return { action: "allow", rule: "default" };
}

const ACTIONS = ["allow", "redact", "warn", "block"];
const STATUSES = ["approved", "tolerated", "unapproved", "unknown"];
const LEVELS = ["off", "standard", "detailed"];

/** Line-based checks that catch the mistakes an editor is likely to make while trying the page. */
export function validatePolicy(yaml: string): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const lines = yaml.split("\n");
  let rule = -1;
  lines.forEach((raw, index) => {
    const line = index + 1;
    if (raw.includes("\t")) issues.push({ path: `line ${line}`, message: "Tabs are not allowed in YAML; indent with spaces.", line });
    if (/^\s*- name:/.test(raw)) rule += 1;
    const action = /^\s*action:\s*(\S+)/.exec(raw)?.[1];
    if (action && !ACTIONS.includes(action)) {
      issues.push({ path: `rules[${rule}].action`, message: `"${action}" is not an action. Use allow, redact, warn or block.`, line });
    }
    const statuses = /^\s*tool_status:\s*\[(.*)\]/.exec(raw)?.[1];
    for (const status of statuses?.split(",").map((item) => item.trim()).filter(Boolean) ?? []) {
      if (!STATUSES.includes(status)) {
        issues.push({ path: `rules[${rule}].when.tool_status`, message: `"${status}" is not a tool status.`, line });
      }
    }
    const level = /^injection_protection:\s*(\S+)/.exec(raw)?.[1];
    if (level && !LEVELS.includes(level)) {
      issues.push({ path: "injection_protection", message: `"${level}" is not a level. Use off, standard or detailed.`, line });
    }
  });
  if (!/^version:/m.test(yaml)) issues.push({ path: "version", message: "The policy needs a version.", line: null });
  if (!/^rules:/m.test(yaml)) issues.push({ path: "rules", message: "The policy needs a list of rules.", line: null });
  return issues;
}

export function readProtectionLevel(yaml: string): "off" | "standard" | "detailed" {
  const level = /^injection_protection:\s*(\S+)/m.exec(yaml)?.[1];
  return level === "off" || level === "detailed" ? level : "standard";
}

export function writeProtectionLevel(yaml: string, level: string): string {
  return yaml.replace(/^injection_protection:.*$/m, `injection_protection: ${level}`);
}

const TYPE_WORDS: readonly (readonly [RegExp, string])[] = [
  [/source code|code/i, "SOURCE_CODE"],
  [/contract/i, "CONTRACT"],
  [/health|medical/i, "HEALTH"],
  [/financ/i, "FINANCIAL"],
  [/\bhr\b|salary|payroll/i, "HR"],
  [/client|customer/i, "CLIENT"],
  [/personal|names?/i, "PERSON"],
];

/** Keyword drafting, standing in for the model: enough to try the draft, review and replay loop. */
export function draftRule(instruction: string, yaml: string): DraftResult {
  const action = ACTIONS.find((candidate) => new RegExp(`\\b${candidate}`, "i").test(instruction)) ?? "warn";
  const types = TYPE_WORDS.filter(([cue]) => cue.test(instruction)).map(([, type]) => type);
  const statuses = STATUSES.filter((status) => new RegExp(`\\b${status}`, "i").test(instruction));
  const name = `draft-${action}-${(types[0] ?? "data").toLowerCase().replace("_", "-")}`;
  const rule = [
    `  - name: ${name}`,
    "    when:",
    "      channel: prompt",
    `      tool_status: [${(statuses.length > 0 ? statuses : ["tolerated", "unapproved", "unknown"]).join(", ")}]`,
    `      data: [${(types.length > 0 ? types : ["CLIENT_CONFIDENTIAL"]).join(", ")}]`,
    `    action: ${action}`,
    "",
  ].join("\n");
  const anchor = yaml.indexOf("  - name: contract-to-unapproved");
  const at = anchor === -1 ? yaml.indexOf("  - name: default") : anchor;
  return {
    yaml: at === -1 ? `${yaml.trimEnd()}\n${rule}` : `${yaml.slice(0, at)}${rule}\n${yaml.slice(at)}`,
    rule_name: name,
    explanation: `Added the rule "${name}" before the first prompt rule, so it is checked ahead of the existing ones. Review it before activating.`,
  };
}
