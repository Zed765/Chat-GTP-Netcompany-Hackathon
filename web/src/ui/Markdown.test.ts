import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

const html = (text: string) => renderToStaticMarkup(createElement(Markdown, { text, leaf: (run: string) => run }));

describe("Markdown", () => {
  it("renders emphasis, code and strike-through inside a paragraph", () => {
    expect(html("**Θέμα:** a *short* `note`, ~~old~~")).toBe(
      '<div class="md"><p><span><strong><span>Θέμα:</span></strong><span> a </span><em><span>short</span></em><span> </span><code>note</code><span>, </span><s><span>old</span></s></span></p></div>',
    );
  });

  it("keeps single line breaks and separates paragraphs", () => {
    expect(html("Dear Maria,\n\nKind regards,\nEleni")).toBe(
      '<div class="md"><p><span><span>Dear Maria,</span></span></p><p><span><span>Kind regards,</span></span><br/><span><span>Eleni</span></span></p></div>',
    );
  });

  it("renders headings, rules and quotes", () => {
    const out = html("# Title\n\n---\n\n> quoted **text**");
    expect(out).toContain("<h4><span>Title</span></h4>");
    expect(out).toContain("<hr/>");
    expect(out).toContain("<blockquote><p><span><span>quoted </span><strong><span>text</span></strong></span></p></blockquote>");
  });

  it("renders bulleted and numbered lists, with a list inside an item", () => {
    const out = html("1. first\n2. second\n   - inner\n\n- a\n- b");
    expect(out).toContain("<ol><li><span><span>first</span></span></li><li><span><span>second</span></span><span><ul><li><span><span>inner</span></span></li></ul></span></li></ol>");
    expect(out).toContain("<ul><li><span><span>a</span></span></li><li><span><span>b</span></span></li></ul>");
  });

  it("renders a fenced block as code, even before it closes", () => {
    expect(html("```python\nprint(**x**)\n```")).toContain("<pre><code>print(**x**)</code></pre>");
    expect(html("```\nstill arriving")).toContain("<pre><code>still arriving</code></pre>");
  });

  it("renders a table", () => {
    const out = html("| Team | Count |\n| --- | ---: |\n| Sales | 4 |");
    expect(out).toContain("<th><span>Team</span></th><th><span>Count</span></th>");
    expect(out).toContain("<td><span>Sales</span></td><td><span>4</span></td>");
  });

  it("leaves placeholders and arithmetic alone", () => {
    expect(html("AFM <AFM_1>, born <DATE_OF_BIRTH_1>, 2 * 3 * 4")).toBe('<div class="md"><p><span><span>AFM &lt;AFM_1&gt;, born &lt;DATE_OF_BIRTH_1&gt;, 2 * 3 * 4</span></span></p></div>');
  });

  it("shows links and images as text and never as elements that load or open an address", () => {
    const out = html("See [the page](https://example.test/?q=secret) ![x](https://example.test/p.png)");
    expect(out).not.toContain("<a");
    expect(out).not.toContain("<img");
    expect(out).toContain("[the page](https://example.test/?q=secret)");
  });
});
