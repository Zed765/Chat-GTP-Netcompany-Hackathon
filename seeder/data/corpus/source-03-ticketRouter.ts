/**
 * Ticket routing for project Pharos (PRJ-PHR-2436).
 *
 * Proprietary and confidential. Property of Aspida Demo Consulting. Do not distribute.
 * Decides which support queue a client request goes to and how fast it must be answered,
 * following the service levels in each client's support contract.
 */

export type Severity = "critical" | "high" | "normal" | "low";
export type Queue = "platform" | "billing" | "integrations" | "general";

export interface Ticket {
  id: string;
  clientId: string;
  subject: string;
  body: string;
  openedAt: Date;
  affectedUsers: number;
  systemDown: boolean;
}

export interface ServiceLevel {
  clientId: string;
  criticalResponseMinutes: number;
  standardResponseMinutes: number;
  coversWeekends: boolean;
}

export interface RoutingDecision {
  queue: Queue;
  severity: Severity;
  respondBy: Date;
  escalate: boolean;
}

const QUEUE_KEYWORDS: Record<Exclude<Queue, "general">, string[]> = {
  platform: ["login", "outage", "slow", "timeout", "σύνδεση", "διακοπή"],
  billing: ["invoice", "payment", "refund", "τιμολόγιο", "πληρωμή"],
  integrations: ["api", "webhook", "export", "sync", "διασύνδεση"],
};

const DEFAULT_LEVEL: Omit<ServiceLevel, "clientId"> = {
  criticalResponseMinutes: 120,
  standardResponseMinutes: 480,
  coversWeekends: false,
};

export function classifySeverity(ticket: Ticket): Severity {
  if (ticket.systemDown) return "critical";
  if (ticket.affectedUsers >= 25) return "high";
  if (ticket.affectedUsers >= 2) return "normal";
  return "low";
}

export function chooseQueue(ticket: Ticket): Queue {
  const text = `${ticket.subject} ${ticket.body}`.toLowerCase();
  let best: Queue = "general";
  let bestHits = 0;
  for (const [queue, keywords] of Object.entries(QUEUE_KEYWORDS)) {
    const hits = keywords.filter((keyword) => text.includes(keyword)).length;
    if (hits > bestHits) {
      best = queue as Queue;
      bestHits = hits;
    }
  }
  return best;
}

function isWeekend(day: Date): boolean {
  return day.getUTCDay() === 0 || day.getUTCDay() === 6;
}

/** Moves a deadline that falls on a weekend to Monday morning, unless weekends are covered. */
export function respondBy(openedAt: Date, minutes: number, coversWeekends: boolean): Date {
  const deadline = new Date(openedAt.getTime() + minutes * 60_000);
  if (coversWeekends) return deadline;
  while (isWeekend(deadline)) {
    deadline.setUTCDate(deadline.getUTCDate() + 1);
    deadline.setUTCHours(7, 0, 0, 0);
  }
  return deadline;
}

export function route(ticket: Ticket, levels: ServiceLevel[]): RoutingDecision {
  const level = levels.find((item) => item.clientId === ticket.clientId) ?? {
    clientId: ticket.clientId,
    ...DEFAULT_LEVEL,
  };
  const severity = classifySeverity(ticket);
  const minutes =
    severity === "critical" ? level.criticalResponseMinutes : level.standardResponseMinutes;
  return {
    queue: chooseQueue(ticket),
    severity,
    respondBy: respondBy(ticket.openedAt, minutes, level.coversWeekends),
    escalate: severity === "critical" || ticket.affectedUsers >= 100,
  };
}

/** Share of tickets answered in time; the monthly Pharos report shows it per client. */
export function complianceRate(decisions: RoutingDecision[], answeredAt: Date[]): number {
  if (decisions.length === 0) return 1;
  const inTime = decisions.filter(
    (decision, index) => answeredAt[index].getTime() <= decision.respondBy.getTime(),
  ).length;
  return inTime / decisions.length;
}

/** The discount the support contract grants when more than three deadlines are missed. */
export function serviceCredit(missed: number, monthlyFee: number, discountPercent: number): number {
  return missed > 3 ? Math.round(monthlyFee * discountPercent) / 100 : 0;
}
