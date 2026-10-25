"use client";
import { useRef, useState } from "react";
import useSWR from "swr";
import { MOCK_MODE, apiGet, apiPost } from "@/lib/api";
import type { Analyze, Business, Hedge, LogEntry, Run } from "@/lib/types";
import { Header, EstimatedBadge } from "@/components/Header";
import {
  ExposureList,
  NotHedgedList,
  ModelCheck,
} from "@/components/ExposureList";
import { HedgeList } from "@/components/HedgeCard";
import { DecisionLog } from "@/components/DecisionLog";
import { StateBoundary } from "@/components/StateBoundary";

export default function Home() {
  const [selectedId, setSelectedId] = useState("taxi");
  const [runningId, setRunningId] = useState<string | null>(null);
  const [runError, setRunError] = useState("");
  const activeBusiness = useRef(selectedId);
  const businesses = useSWR<Business[]>(["/businesses", "all"], () =>
    apiGet("/businesses"),
  );
  const business = businesses.data?.find((row) => row.id === selectedId);
  const base = `/businesses/${encodeURIComponent(selectedId)}`;
  const analyze = useSWR<Analyze>(["analyze", selectedId], () =>
    apiPost(`${base}/analyze`),
  );
  const hedges = useSWR<Hedge[]>(["hedges", selectedId], () =>
    apiGet(
      `${base}/hedges${business ? `?week_of=${business.budget.week_start}` : ""}`,
    ),
  );
  const decisions = useSWR<LogEntry[]>(["decisions", selectedId], () =>
    apiGet(`${base}/decisions`),
  );
  async function refresh() {
    await Promise.all([
      hedges.mutate(),
      businesses.mutate(),
      decisions.mutate(),
    ]);
  }
  async function runDesk() {
    const id = selectedId;
    setRunningId(id);
    setRunError("");
    try {
      const accepted = await apiPost<{ run_id: string }>(`${base}/desk/run`);
      for (let attempt = 0; attempt < 30; attempt++) {
        const run = await apiGet<Run>(
          `/runs/${encodeURIComponent(accepted.run_id)}`,
        );
        if (run.status === "failed")
          throw new Error(run.error ?? "The desk run failed. Please retry.");
        if (run.status === "done") {
          await refresh();
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      throw new Error(
        "The desk is taking longer than expected. Please run it again.",
      );
    } catch (err) {
      if (activeBusiness.current === id)
        setRunError(
          err instanceof Error ? err.message : "Unable to run the desk.",
        );
    } finally {
      setRunningId(null);
    }
  }
  return (
    <main>
      {MOCK_MODE && (
        <div className="mock-banner">MOCK DATA · Demonstration only</div>
      )}
      <StateBoundary
        loading={businesses.isLoading}
        error={businesses.error}
        retry={() => businesses.mutate()}
      >
        <Header
          businesses={businesses.data ?? []}
          selectedId={selectedId}
          onSelect={(id) => {
            activeBusiness.current = id;
            setSelectedId(id);
            setRunError("");
          }}
          onRun={runDesk}
          running={runningId !== null}
        />
      </StateBoundary>
      <div className="intro">
        <div>
          <span className="eyebrow">Your weekly desk</span>
          <h2>A little more certainty.</h2>
          <p>Measured risks. Clear costs. Every decision stays yours.</p>
        </div>
        <span className="badge">No real orders are placed</span>
      </div>
      {runError && (
        <div role="alert" className="run-error">
          {runError}{" "}
          <button onClick={runDesk} disabled={runningId !== null}>
            Retry run
          </button>
        </div>
      )}
      <div className="dashboard" key={selectedId}>
        <section
          className="panel exposure-panel"
          aria-label="Revenue exposures"
        >
          <div className="section-heading">
            <h2>What moves revenue</h2>
            {business && (
              <EstimatedBadge
                kind={business.estimated ? "estimated" : "real"}
              />
            )}
          </div>
          <StateBoundary
            loading={analyze.isLoading}
            error={analyze.error}
            retry={() => analyze.mutate()}
          >
            {analyze.data && (
              <>
                <ExposureList exposures={analyze.data.exposures} />
                <NotHedgedList dropped={analyze.data.dropped} />
                <ModelCheck
                  data={analyze.data.model_check}
                  r2={analyze.data.r2_holdout}
                />
              </>
            )}
          </StateBoundary>
        </section>
        <section className="hedges-panel" aria-label="Hedge decisions">
          <StateBoundary
            loading={hedges.isLoading}
            error={hedges.error}
            retry={() => hedges.mutate()}
          >
            <HedgeList hedges={hedges.data ?? []} onChanged={refresh} />
          </StateBoundary>
        </section>
        <section className="panel log-panel" aria-label="Decision log">
          <div className="section-heading">
            <h2>Decision log</h2>
            <span className="live-dot" aria-hidden="true" />
          </div>
          <p className="muted">Every decision has a receipt.</p>
          <StateBoundary
            loading={decisions.isLoading}
            error={decisions.error}
            retry={() => decisions.mutate()}
          >
            <DecisionLog decisions={decisions.data ?? []} />
          </StateBoundary>
        </section>
      </div>
      <footer>
        Protection for the business you’re building. · The owner always decides.
      </footer>
    </main>
  );
}
