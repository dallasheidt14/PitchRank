'use client';

import { Component, ReactNode } from 'react';
import { MergeTeamsDialog } from './MergeTeamsDialog';

interface MergeTeamsDialogWrapperProps {
  currentTeamId: string;
  currentTeamName: string;
  currentTeamAgeGroup?: string | null;
  currentTeamGender?: string | null;
  currentTeamStateCode?: string | null;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

class ErrorBoundary extends Component<
  { children: ReactNode },
  ErrorBoundaryState
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('MergeTeamsDialog error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      // Return a fallback button that doesn't do anything
      return (
        <button
          type="button"
          className="inline-flex items-center justify-center gap-2 rounded-md border border-input bg-background px-3 py-2 text-sm font-medium ring-offset-background transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
          disabled
          title="Merge feature temporarily unavailable"
        >
          <span>Merge Dupe Teams</span>
        </button>
      );
    }

    return this.props.children;
  }
}

export function MergeTeamsDialogWrapper(props: MergeTeamsDialogWrapperProps) {
  return (
    <ErrorBoundary>
      <MergeTeamsDialog {...props} />
    </ErrorBoundary>
  );
}

