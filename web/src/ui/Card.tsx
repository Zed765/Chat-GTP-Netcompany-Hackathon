import { type ReactNode, useId } from "react";

interface CardProps {
  title?: ReactNode;
  actions?: ReactNode;
  /** Heading level of the title; pages use 2 for sections and 3 for cards inside them. */
  level?: 2 | 3;
  className?: string;
  children: ReactNode;
}

/** A titled surface. With a title it is a labelled region, so screen-reader users can jump to it. */
export function Card({ title, actions, level = 2, className, children }: CardProps) {
  const titleId = useId();
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <section className={`card ${className ?? ""}`.trim()} aria-labelledby={title ? titleId : undefined}>
      {(title || actions) && (
        <div className="card-header">
          {title && <Heading id={titleId}>{title}</Heading>}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}
