import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
export function StateBoundary({
  loading,
  error,
  retry,
  children,
}: {
  loading: boolean;
  error?: Error;
  retry: () => void;
  children: ReactNode;
}) {
  if (error)
    return (
      <div role="alert" className="state">
        <p>{error.message}</p>
        <Button variant="outline" onClick={retry}>
          Retry
        </Button>
      </div>
    );
  if (loading)
    return (
      <div role="status" aria-label="Loading region" className="skeleton">
        <span>Loading…</span>
      </div>
    );
  return children;
}
