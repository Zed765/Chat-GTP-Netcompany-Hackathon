import { segmentText } from "../../lib/spans";
import type { Turn } from "./turns";

/** A value the firewall swapped for a placeholder somewhere in the conversation. */
export interface Masked {
  value: string;
  dataType: string;
  placeholder: string;
}

/**
 * What has been masked by the end of each turn. A placeholder belongs to the conversation, not
 * to one message: a later answer can bring back a value that an earlier message put in the vault.
 */
export function maskedByTurn(turns: readonly Turn[]): Masked[][] {
  const vault = new Map<string, Masked>();
  return turns.map((turn) => {
    for (const segment of turn.trace ? segmentText(turn.prompt, turn.trace.spans) : []) {
      if (segment.span?.placeholder) {
        vault.set(segment.text, { value: segment.text, dataType: segment.span.data_type, placeholder: segment.span.placeholder });
      }
    }
    return [...vault.values()];
  });
}
