import { type ReactNode, useEffect } from "react";

interface PageHeaderProps {
  title: string;
  /** Keep the title for the browser tab and screen readers, but show no header. */
  hideTitle?: boolean;
  actions?: ReactNode;
}

export function PageHeader({ title, hideTitle, actions }: PageHeaderProps) {
  useEffect(() => {
    document.title = `${title} · A.S.P.I.D.A.`;
  }, [title]);

  if (hideTitle) return <h1 className="sr-only">{title}</h1>;
  return (
    <header className="page-header">
      <h1>{title}</h1>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}
