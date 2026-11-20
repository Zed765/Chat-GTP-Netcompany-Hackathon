import type { Principal } from "../../api/types";

/** The fictional demo organisation: the same teams and sign-in users as the gateway's. */
export const TEAMS = ["Sales", "Legal", "Finance", "Engineering", "HR", "Customer Support"] as const;

export type Team = (typeof TEAMS)[number];

export const USERS: readonly Principal[] = [
  { user_id: "v.tsioutsias", display_name: "Vassilis Tsioutsias", team: "Sales", role: "employee" },
  { user_id: "a.bilas", display_name: "Apostolos Bilas", team: "Security", role: "admin" },
];

/** A small deterministic generator, so the sample data is the same on every load. */
export function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let mixed = Math.imul(state ^ (state >>> 15), 1 | state);
    mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed;
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
}

/** Picks an item with probability proportional to its weight. */
export function weighted<T>(random: () => number, items: readonly (readonly [T, number])[]): T {
  const total = items.reduce((sum, [, weight]) => sum + weight, 0);
  let roll = random() * total;
  for (const [item, weight] of items) {
    roll -= weight;
    if (roll <= 0) return item;
  }
  return (items[items.length - 1] as readonly [T, number])[0];
}

export const DAY_MS = 86_400_000;

/** "Now" for the sample data: the load time, rounded down to the minute. */
export function mockNow(): Date {
  return new Date(Math.floor(Date.now() / 60_000) * 60_000);
}

export function isoMinus(now: Date, ms: number): string {
  return new Date(now.getTime() - ms).toISOString();
}
