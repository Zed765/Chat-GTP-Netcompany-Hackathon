import type { ReactNode } from "react";

/**
 * Markdown as model answers use it, built as React elements and never as HTML.
 *
 * Links and images are shown as text and never loaded or made clickable: an address in a
 * model's answer can carry data out, and here that answer may hold restored values.
 * Underscores are not emphasis, so a placeholder such as <DATE_OF_BIRTH_1> stays whole.
 */
interface MarkdownProps {
  text: string;
  /** Renders a run of plain text, with whatever highlighting the caller applies. */
  leaf: (text: string) => ReactNode;
}

type Leaf = MarkdownProps["leaf"];

const INLINE = /(`[^`\n]+`)|(\*\*(?!\s)[^\n]+?(?<!\s)\*\*)|(\*(?![\s*])[^*\n]+?(?<![\s*])\*)|(~~[^~\n]+?~~)|(!?\[[^\]\n]*\]\([^)\s]+\))/;
const HEADING = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/;
const FENCE = /^ {0,3}(```|~~~)/;
const QUOTE = /^ {0,3}>\s?/;
const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function inline(text: string, leaf: Leaf): ReactNode[] {
  const nodes: ReactNode[] = [];
  let rest = text;
  for (let key = 0; rest; key += 2) {
    const match = INLINE.exec(rest);
    if (!match) {
      nodes.push(<span key={key}>{leaf(rest)}</span>);
      break;
    }
    if (match.index > 0) nodes.push(<span key={key}>{leaf(rest.slice(0, match.index))}</span>);
    const [token, code, strong, emphasis, strike, link] = match;
    if (code) nodes.push(<code key={key + 1}>{leaf(code.slice(1, -1))}</code>);
    else if (strong) nodes.push(<strong key={key + 1}>{inline(strong.slice(2, -2), leaf)}</strong>);
    else if (emphasis) nodes.push(<em key={key + 1}>{inline(emphasis.slice(1, -1), leaf)}</em>);
    else if (strike) nodes.push(<s key={key + 1}>{inline(strike.slice(2, -2), leaf)}</s>);
    else if (link) nodes.push(<span key={key + 1}>{leaf(link)}</span>);
    rest = rest.slice(match.index + token.length);
  }
  return nodes;
}

const cells = (row: string) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());

const isBlockStart = (line: string) => HEADING.test(line) || RULE.test(line) || FENCE.test(line) || QUOTE.test(line) || ITEM.test(line);

/** The items of one list, starting at `start`; deeper-indented items become a list inside the item before them. */
function list(lines: string[], start: number, leaf: Leaf): [ReactNode, number] {
  const [, indent = "", marker = "-"] = ITEM.exec(lines[start] ?? "") ?? [];
  const ordered = /\d/.test(marker);
  const items: ReactNode[] = [];
  let at = start;
  while (at < lines.length) {
    const match = ITEM.exec(lines[at] ?? "");
    if (!match || (match[1] ?? "").length < indent.length) break;
    if ((match[1] ?? "").length > indent.length || /\d/.test(match[2] ?? "") !== ordered) break;
    const content: ReactNode[] = [<span key="text">{inline(match[3] ?? "", leaf)}</span>];
    at += 1;
    while (at < lines.length) {
      const next = ITEM.exec(lines[at] ?? "");
      if (next && (next[1] ?? "").length > indent.length) {
        const [nested, end] = list(lines, at, leaf);
        content.push(<span key={at}>{nested}</span>);
        at = end;
      } else if (!next && lines[at]?.trim() && /^\s+/.test(lines[at] ?? "") && !isBlockStart(lines[at] ?? "")) {
        content.push(<br key={`br-${at}`} />, <span key={at}>{inline((lines[at] ?? "").trim(), leaf)}</span>);
        at += 1;
      } else break;
    }
    items.push(<li key={at}>{content}</li>);
    // One blank line between items does not end the list.
    if (!lines[at]?.trim() && ITEM.test(lines[at + 1] ?? "")) at += 1;
  }
  const node = ordered ? <ol>{items}</ol> : <ul>{items}</ul>;
  return [node, at];
}

function blocks(lines: string[], leaf: Leaf): ReactNode[] {
  const out: ReactNode[] = [];
  let at = 0;
  while (at < lines.length) {
    const line = lines[at] ?? "";
    const heading = HEADING.exec(line);
    const fence = FENCE.exec(line);
    if (!line.trim()) {
      at += 1;
    } else if (fence) {
      // A fence that never closes is still code: the answer may be arriving.
      let end = at + 1;
      while (end < lines.length && !(lines[end] ?? "").trimStart().startsWith(fence[1] ?? "```")) end += 1;
      out.push(
        <pre key={at}>
          <code>{leaf(lines.slice(at + 1, end).join("\n"))}</code>
        </pre>,
      );
      at = end + 1;
    } else if (heading) {
      const Tag = (["h4", "h4", "h5", "h6", "h6", "h6"] as const)[(heading[1] ?? "#").length - 1] ?? "h6";
      out.push(<Tag key={at}>{inline(heading[2] ?? "", leaf)}</Tag>);
      at += 1;
    } else if (RULE.test(line)) {
      out.push(<hr key={at} />);
      at += 1;
    } else if (QUOTE.test(line)) {
      let end = at;
      while (end < lines.length && QUOTE.test(lines[end] ?? "")) end += 1;
      out.push(<blockquote key={at}>{blocks(lines.slice(at, end).map((quoted) => quoted.replace(QUOTE, "")), leaf)}</blockquote>);
      at = end;
    } else if (ITEM.test(line)) {
      const [node, end] = list(lines, at, leaf);
      out.push(<div key={at}>{node}</div>);
      at = end;
    } else if (line.includes("|") && TABLE_RULE.test(lines[at + 1] ?? "")) {
      let end = at + 2;
      while (end < lines.length && (lines[end] ?? "").includes("|") && (lines[end] ?? "").trim()) end += 1;
      out.push(
        <div key={at} className="md-table">
          <table>
            <thead>
              <tr>
                {cells(line).map((cell, index) => (
                  <th key={index}>{inline(cell, leaf)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {lines.slice(at + 2, end).map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {cells(row).map((cell, index) => (
                    <td key={index}>{inline(cell, leaf)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      at = end;
    } else {
      // Models write letters and drafts with single line breaks that matter, so they are kept.
      const paragraph: ReactNode[] = [];
      const first = at;
      while (at < lines.length && (lines[at] ?? "").trim() && (at === first || !isBlockStart(lines[at] ?? ""))) {
        if (at > first) paragraph.push(<br key={`br-${at}`} />);
        paragraph.push(<span key={at}>{inline(lines[at] ?? "", leaf)}</span>);
        at += 1;
      }
      out.push(<p key={first}>{paragraph}</p>);
    }
  }
  return out;
}

export function Markdown({ text, leaf }: MarkdownProps) {
  return <div className="md">{blocks(text.replaceAll("\r\n", "\n").split("\n"), leaf)}</div>;
}
