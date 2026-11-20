import type { ReactNode } from "react";
import type { Resource } from "../hooks/useResource";
import { Button } from "./Button";
import { Icon, type IconName } from "./Icon";

/** Shown only when loading takes long enough to read it: a message that flashes by is noise. */
export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}…</span>
    </div>
  );
}

interface EmptyStateProps {
  icon?: IconName;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ icon = "info", title, children, action }: EmptyStateProps) {
  return (
    <div className="state">
      <Icon name={icon} size={28} />
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ title = "This could not be loaded", message, onRetry }: ErrorStateProps) {
  return (
    <div className="state" role="alert">
      <Icon name="alert" size={28} />
      <h3>{title}</h3>
      <p>{message}</p>
      {onRetry && (
        <Button icon="refresh" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

interface ResourceViewProps<T> {
  resource: Resource<T>;
  /** What is loading, for the status text: "tools", "settings". */
  label?: string;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  children: (data: T) => ReactNode;
}

/** Renders the loading, error, empty or ready view of a resource, so no page forgets one. */
export function ResourceView<T>({ resource, label, isEmpty, empty, children }: ResourceViewProps<T>) {
  if (resource.status === "loading") return <Loading label={label ? `Loading ${label}` : undefined} />;
  if (resource.status === "error") {
    return <ErrorState message={resource.error.message} onRetry={resource.reload} />;
  }
  if (isEmpty?.(resource.data)) return <>{empty}</>;
  return (
    <div className={resource.refreshing ? "refreshing" : undefined} aria-busy={resource.refreshing || undefined}>
      {children(resource.data)}
    </div>
  );
}
