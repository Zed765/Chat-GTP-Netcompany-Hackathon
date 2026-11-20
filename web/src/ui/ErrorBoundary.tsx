import { Component, type ReactNode } from "react";
import { ErrorState } from "./States";

interface Props {
  /** Changing this value clears a caught error, so navigating away recovers the app. */
  resetKey: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
  resetKey: string;
}

/** Catches a page that fails to render or to download, without taking the shell down. */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey === state.resetKey ? null : { error: null, resetKey: props.resetKey };
  }

  override render() {
    if (!this.state.error) return this.props.children;
    return (
      <ErrorState
        title="This page could not be shown"
        message="Something went wrong while loading or drawing this page. Reloading usually fixes it."
        onRetry={() => window.location.reload()}
      />
    );
  }
}
