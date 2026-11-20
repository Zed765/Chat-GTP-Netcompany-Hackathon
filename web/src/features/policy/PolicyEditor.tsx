import { type Ref, useImperativeHandle, useRef } from "react";

export interface PolicyEditorHandle {
  /** Moves the cursor to a line (1-based) and selects it, so a validation issue can be jumped to. */
  goToLine: (line: number) => void;
}

interface PolicyEditorProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  /** Lines (1-based) that have a validation issue. */
  issueLines: ReadonlySet<number>;
  describedBy?: string;
  invalid: boolean;
  ref?: Ref<PolicyEditorHandle>;
}

/** A plain-text YAML editor with line numbers. Lines with a problem are marked in the gutter. */
export function PolicyEditor({ id, value, onChange, issueLines, describedBy, invalid, ref }: PolicyEditorProps) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const gutter = useRef<HTMLDivElement>(null);
  const lineCount = value.split("\n").length;

  useImperativeHandle(ref, () => ({
    goToLine(line) {
      const element = textarea.current;
      if (!element) return;
      const lines = element.value.split("\n");
      const start = lines.slice(0, line - 1).reduce((offset, text) => offset + text.length + 1, 0);
      element.focus();
      element.setSelectionRange(start, start + (lines[line - 1]?.length ?? 0));
      const lineHeight = Number.parseFloat(getComputedStyle(element).lineHeight);
      element.scrollTop = Math.max(0, (line - 4) * lineHeight);
    },
  }));

  return (
    <div className="editor">
      <div className="editor-gutter" ref={gutter} aria-hidden="true">
        {Array.from({ length: lineCount }, (_, index) => (
          <span key={index} className={issueLines.has(index + 1) ? "editor-line editor-line-issue" : "editor-line"}>
            {index + 1}
          </span>
        ))}
      </div>
      <textarea
        id={id}
        ref={textarea}
        className="editor-text"
        value={value}
        wrap="off"
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        aria-describedby={describedBy}
        aria-invalid={invalid}
        onChange={(event) => onChange(event.target.value)}
        onScroll={(event) => {
          if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop;
        }}
      />
    </div>
  );
}
