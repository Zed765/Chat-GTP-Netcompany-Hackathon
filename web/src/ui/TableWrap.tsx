import type { ReactNode } from "react";

interface TableWrapProps {
  /** Names the scrolling area for assistive technology. */
  label?: string;
  className?: string;
  children: ReactNode;
}

/**
 * The frame around a table. A wide table scrolls sideways inside it instead of widening the
 * page, and the frame can take focus so that the scrolling also works from the keyboard.
 */
export function TableWrap({ label = "Table", className, children }: TableWrapProps) {
  return (
    // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrollable area must be reachable by keyboard
    <div className={className ? `table-wrap ${className}` : "table-wrap"} role="group" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}
