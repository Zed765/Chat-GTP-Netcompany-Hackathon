/**
 * Reads a server-sent event stream and yields the `data` payload of each event.
 *
 * Bytes are decoded incrementally, so a multi-byte character (Greek, for example) split
 * across two network chunks is still read correctly, as is an event split across chunks.
 */
export async function* sseData(stream: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let data: string[] = [];

  function* takeLines(final: boolean): Generator<string> {
    for (;;) {
      const match = /\r\n|\n|\r/.exec(buffer);
      // A trailing "\r" may be the first half of "\r\n" still in transit.
      if (!match || (!final && match[0] === "\r" && match.index === buffer.length - 1)) break;
      const line = buffer.slice(0, match.index);
      buffer = buffer.slice(match.index + match[0].length);
      if (line === "") {
        if (data.length > 0) yield data.join("\n");
        data = [];
      } else if (line.startsWith("data:")) {
        data.push(line.slice(line.charAt(5) === " " ? 6 : 5));
      }
    }
  }

  try {
    for (;;) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      yield* takeLines(done);
      if (done) break;
    }
    if (buffer.startsWith("data:")) data.push(buffer.slice(buffer.charAt(5) === " " ? 6 : 5));
    if (data.length > 0) yield data.join("\n");
  } finally {
    reader.releaseLock();
  }
}
