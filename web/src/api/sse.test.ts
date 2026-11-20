import { describe, expect, it } from "vitest";
import { sseData } from "./sse";

/** A byte stream that delivers `bytes` in pieces cut at the given offsets. */
function streamOf(bytes: Uint8Array, cuts: readonly number[]): ReadableStream<Uint8Array> {
  const edges = [0, ...cuts, bytes.length];
  return new ReadableStream({
    start(controller) {
      for (let index = 0; index < edges.length - 1; index += 1) {
        const piece = bytes.slice(edges[index], edges[index + 1]);
        if (piece.length > 0) controller.enqueue(piece);
      }
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<string[]> {
  const events: string[] = [];
  for await (const data of sseData(stream)) events.push(data);
  return events;
}

const encode = (text: string) => new TextEncoder().encode(text);

describe("sseData", () => {
  it("yields the data of each event", async () => {
    const stream = streamOf(encode('data: {"a":1}\n\ndata: {"b":2}\n\ndata: [DONE]\n\n'), []);
    expect(await collect(stream)).toEqual(['{"a":1}', '{"b":2}', "[DONE]"]);
  });

  it("gives the same events wherever the network cuts the bytes", async () => {
    const text = 'data: {"text":"Αγαπητή κυρία Παπαδοπούλου"}\r\n\r\n: keep-alive\n\nevent: note\ndata: first line\ndata: second line\n\ndata:no-space\n\n';
    const bytes = encode(text);
    const expected = ['{"text":"Αγαπητή κυρία Παπαδοπούλου"}', "first line\nsecond line", "no-space"];
    // Every single cut point, which includes the middle of each two-byte Greek letter and of "\r\n".
    for (let cut = 1; cut < bytes.length; cut += 1) {
      expect(await collect(streamOf(bytes, [cut]))).toEqual(expected);
    }
    // And one byte at a time.
    expect(await collect(streamOf(bytes, Array.from({ length: bytes.length - 1 }, (_, index) => index + 1)))).toEqual(expected);
  });

  it("keeps a final event that has no blank line after it", async () => {
    expect(await collect(streamOf(encode("data: one\n\ndata: two"), []))).toEqual(["one", "two"]);
  });

  it("ignores comments and fields other than data", async () => {
    expect(await collect(streamOf(encode(": hello\nid: 7\nretry: 100\n\ndata: kept\n\n"), []))).toEqual(["kept"]);
  });
});
