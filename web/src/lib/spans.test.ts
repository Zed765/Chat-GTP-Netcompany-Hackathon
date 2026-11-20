import { describe, expect, it } from "vitest";
import { countPlaceholders, splitPlaceholders } from "./placeholders";
import { segmentRestored, segmentText, spanValues } from "./spans";

const span = (start: number, end: number, data_type = "PERSON") => ({ start, end, data_type });

describe("segmentText", () => {
  it("cuts the text into plain runs and spans, in order", () => {
    const text = "Call Maria on 210 555 0142 today";
    const segments = segmentText(text, [span(14, 26, "PHONE"), span(5, 10)]);
    expect(segments.map((segment) => [segment.text, segment.span?.data_type])).toEqual([
      ["Call ", undefined],
      ["Maria", "PERSON"],
      [" on ", undefined],
      ["210 555 0142", "PHONE"],
      [" today", undefined],
    ]);
    expect(segments.map((segment) => segment.text).join("")).toBe(text);
  });

  it("highlights Greek text at the right letters", () => {
    const text = "Η κα Μαρία Παπαδοπούλου, ΑΦΜ 094872613.";
    const segments = segmentText(text, [span(5, 23), span(29, 38, "AFM")]);
    expect(segments.filter((segment) => segment.span).map((segment) => segment.text)).toEqual(["Μαρία Παπαδοπούλου", "094872613"]);
  });

  it("reads offsets as code points, so an emoji before a span does not shift it", () => {
    // "👍" is one code point but two UTF-16 units.
    const text = "👍 ok, ask Maria 🙂 now";
    const start = [...text].indexOf("M");
    const segments = segmentText(text, [span(start, start + 5)]);
    expect(segments.find((segment) => segment.span)?.text).toBe("Maria");
    expect(segments.map((segment) => segment.text).join("")).toBe(text);
  });

  it("skips a span that overlaps an earlier one, is empty or runs backwards", () => {
    const text = "Maria Papadopoulou";
    const segments = segmentText(text, [span(0, 18), span(6, 18), span(3, 3), span(9, 4)]);
    expect(segments).toHaveLength(1);
    expect(segments[0]?.text).toBe(text);
  });

  it("clamps a span that runs past the end of the text", () => {
    expect(segmentText("Maria", [span(0, 99)]).map((segment) => segment.text)).toEqual(["Maria"]);
  });

  it("returns the whole text when there are no spans, and nothing for empty text", () => {
    expect(segmentText("plain", [])).toEqual([{ text: "plain" }]);
    expect(segmentText("", [])).toEqual([]);
  });
});

describe("spanValues and segmentRestored", () => {
  it("finds the user's own values in the restored answer", () => {
    const prompt = "Reply to Maria Papadopoulou, AFM 094872613.";
    const values = spanValues(prompt, [span(9, 27), span(33, 42, "AFM")]);
    expect(values).toEqual([
      { value: "Maria Papadopoulou", dataType: "PERSON" },
      { value: "094872613", dataType: "AFM" },
    ]);
    const answer = "Dear Maria Papadopoulou, your tax number 094872613 is on file. Regards to Maria Papadopoulou.";
    const restored = segmentRestored(answer, values);
    expect(restored.filter((segment) => segment.span).map((segment) => segment.text)).toEqual(["Maria Papadopoulou", "094872613", "Maria Papadopoulou"]);
    expect(restored.map((segment) => segment.text).join("")).toBe(answer);
  });

  it("prefers the longer value where one contains another", () => {
    const restored = segmentRestored("Maria Papadopoulou and Maria", [
      { value: "Maria", dataType: "PERSON" },
      { value: "Maria Papadopoulou", dataType: "PERSON" },
    ]);
    expect(restored.filter((segment) => segment.span).map((segment) => segment.text)).toEqual(["Maria Papadopoulou", "Maria"]);
  });

  it("ignores blank values", () => {
    expect(segmentRestored("text", [{ value: " ", dataType: "PERSON" }])).toEqual([{ text: "text" }]);
  });
});

describe("placeholders", () => {
  it("splits masked text into text and typed placeholders", () => {
    const parts = splitPlaceholders("Dear <PERSON_1>, card <ID_CARD_12> and key <SECRET_REDACTED>.");
    expect(parts.filter((part) => part.kind === "placeholder")).toEqual([
      { kind: "placeholder", text: "<PERSON_1>", dataType: "PERSON" },
      { kind: "placeholder", text: "<ID_CARD_12>", dataType: "ID_CARD" },
      { kind: "placeholder", text: "<SECRET_REDACTED>", dataType: "SECRET" },
    ]);
    expect(parts.map((part) => part.text).join("")).toBe("Dear <PERSON_1>, card <ID_CARD_12> and key <SECRET_REDACTED>.");
  });

  it("accepts a company's own type, also in Greek capitals", () => {
    expect(splitPlaceholders("Το <ΕΡΓΟ_3> και το <PROJECT_1>").filter((part) => part.kind === "placeholder").map((part) => part.kind === "placeholder" && part.dataType)).toEqual([
      "ΕΡΓΟ",
      "PROJECT",
    ]);
  });

  it("leaves ordinary angle brackets alone", () => {
    expect(countPlaceholders("if a < b and b > c, <b>bold</b>, <person_1>, <PERSON>")).toBe(0);
    expect(countPlaceholders("<AFM_1> <AFM_1> <IBAN_2>")).toBe(3);
  });
});
