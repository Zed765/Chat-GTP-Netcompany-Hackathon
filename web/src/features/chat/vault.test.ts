import { expect, test } from "vitest";
import type { Turn } from "./turns";
import { maskedByTurn } from "./vault";

/** A turn with only the fields the vault view reads. */
function turn(prompt: string, spans: { start: number; end: number; data_type: string; placeholder: string | null }[]): Turn {
  return { prompt, trace: { spans } } as unknown as Turn;
}

test("a later turn still knows what an earlier one masked", () => {
  const first = "Reply to Maria Papadopoulou, AFM 094014201";
  const turns = [
    turn(first, [
      { start: 9, end: 27, data_type: "PERSON", placeholder: "<PERSON_1>" },
      { start: 33, end: 42, data_type: "AFM", placeholder: "<AFM_1>" },
    ]),
    turn("Now translate your reply into Greek for her.", []),
  ];

  const [afterFirst, afterSecond] = maskedByTurn(turns);

  expect(afterFirst).toEqual([
    { value: "Maria Papadopoulou", dataType: "PERSON", placeholder: "<PERSON_1>" },
    { value: "094014201", dataType: "AFM", placeholder: "<AFM_1>" },
  ]);
  expect(afterSecond).toEqual(afterFirst);
});

test("a value that was found but not masked is not in the vault", () => {
  const turns = [turn("CONFIDENTIAL notes", [{ start: 0, end: 12, data_type: "CONFIDENTIAL_MARKER", placeholder: null }])];
  expect(maskedByTurn(turns)).toEqual([[]]);
});
