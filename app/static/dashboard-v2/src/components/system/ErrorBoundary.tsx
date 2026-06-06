import React from "react";

import { Button } from "../ui/button";

type Props = {
  children: React.ReactNode;
};

type State = {
  error: Error | null;
};

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[dashboard-v2] uncaught render error", error, info);
  }

  handleRetry = () => {
    this.setState({ error: null });
  };

  render() {
    if (!this.state.error) {
      return this.props.children;
    }

    return (
      <div className="min-h-screen bg-page text-primary px-6 py-10">
        <main className="mx-auto max-w-3xl">
          <section className="rounded-2xl border border-hairline bg-raised p-6 shadow-[0_8px_24px_rgba(15,23,42,0.08)]">
            <p className="panel-kicker">Recovery</p>
            <h2 className="m-0 text-2xl font-semibold tracking-[-0.02em] text-primary">
              Something went wrong in the operator surface
            </h2>
            <p className="mt-3 text-sm leading-6 text-secondary">
              {this.state.error.message || "Component render failed."}
            </p>
            <div className="mt-5 flex">
              <Button onClick={this.handleRetry}>Retry</Button>
            </div>
          </section>
        </main>
      </div>
    );
  }
}
