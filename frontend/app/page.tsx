"use client";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { MOCK_MODE, apiGet, apiPost, errorCode } from "@/lib/api";
import type {
  Analyze,
  Backtest,
  Business,
  Health,
  Hedge,
  Ledger,
  LogEntry,
  ReconBenchmark,
  Run,
  SampleFlag,
} from "@/lib/types";
import { Header, EstimatedBadge } from "@/components/Header";
import {
  ExposureList,
  NotHedgedList,
  ModelCheck,
} from "@/components/ExposureList";
import { HedgeList } from "@/components/HedgeCard";
import { DecisionLog } from "@/components/DecisionLog";
import { StateBoundary } from "@/components/StateBoundary";
import { BacktestNotReady, BacktestPanel } from "@/components/BacktestPanel";
import { LedgerTab } from "@/components/LedgerTab";
import { ChatDrawer } from "@/components/ChatDrawer";
import { SettingsDrawer } from "@/components/SettingsDrawer";
import {
  DEMO_ID,
  DemoDesk,
  DemoUploadDrawer,
  useDemo,
  type QuickBooksReturn,
} from "@/components/DemoDesk";

export default function Home() {
  const [selectedId, setSelectedId] = useState("taxi");
  const [runningId, setRunningId] = useState<string | null>(null);
  const [runError, setRunError] = useState("");
  const [tab, setTab] = useState<"backtest" | "ledger">("backtest");
  const [drawer, setDrawer] = useState<"chat" | "settings" | "upload" | null>(
    null,
  );
  const activeBusiness = useRef(selectedId);
  // Back from QuickBooks' OAuth consent (?qbo=connected|error): reopen the drawer, which
  // re-reads the connection, and drop the flag from the URL.
  const [qboReturn, setQboReturn] = useState<QuickBooksReturn>(null);
  useEffect(() => {
    const url = new URL(window.location.href);
    const flag = url.searchParams.get("qbo");
    if (flag !== "connected" && flag !== "error") return;
    setQboReturn(flag);
    setDrawer("upload");
    url.searchParams.delete("qbo");
    window.history.replaceState(window.history.state, "", url.toString());
  }, []);
  const businesses = useSWR<Business[]>(["/businesses", "all"], () =>
    apiGet("/businesses"),
  );
  // Scripted upload demo: a client-only business; no API calls for it.
  const demo = useDemo();
  const isDemo = selectedId === DEMO_ID;
  const live = (key: string): [string, string] | null =>
    isDemo ? null : [key, selectedId];
  const allBusinesses = [
    ...(businesses.data ?? []),
    ...(demo.business ? [demo.business] : []),
  ];
  const business = allBusinesses.find((row) => row.id === selectedId);
  const base = `/businesses/${encodeURIComponent(selectedId)}`;
  const analyze = useSWR<Analyze>(live("analyze"), () =>
    apiPost(`${base}/analyze`),
  );
  const hedges = useSWR<Hedge[]>(live("hedges"), () =>
    apiGet(
      `${base}/hedges${business ? `?week_of=${business.budget.week_start}` : ""}`,
    ),
  );
  const decisions = useSWR<LogEntry[]>(live("decisions"), () =>
    apiGet(`${base}/decisions`),
  );
  const backtest = useSWR<Backtest>(live("backtest"), () =>
    apiGet(`${base}/backtest`),
  );
  const ledger = useSWR<Ledger>(tab === "ledger" ? live("ledger") : null, () =>
    apiGet(`${base}/ledger`),
  );
  // Planted-error benchmark (simulated, same for every business); optional on the Books tab.
  const benchmark = useSWR<ReconBenchmark>(
    tab === "ledger" && !isDemo ? ["/benchmarks/reconciliation", "all"] : null,
    () => apiGet("/benchmarks/reconciliation"),
    { shouldRetryOnError: false },
  );
  const health = useSWR<Health>(["/health", "all"], () => apiGet("/health"), {
    shouldRetryOnError: false,
  });
  // Seeded sample week (M3 review): /health lists the businesses still showing
  // seeded sample hedges; a hedge may also carry the flag. Missing means false / [].
  const sampleWeek =
    (health.data?.sample_businesses ?? []).includes(selectedId) ||
    (hedges.data ?? []).some(
      (row) => (row as Hedge & SampleFlag).sample_week === true,
    );
  async function refreshAfterSettings() {
    const [, next] = await Promise.all([
      analyze.mutate(),
      hedges.mutate(),
      businesses.mutate(),
      decisions.mutate(),
    ]);
    return next;
  }
  async function refresh() {
    await Promise.all([
      hedges.mutate(),
      businesses.mutate(),
      decisions.mutate(),
    ]);
  }
  function select(id: string) {
    activeBusiness.current = id;
    setSelectedId(id);
    setRunError("");
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
          businesses={allBusinesses}
          selectedId={selectedId}
          onSelect={select}
          onRun={runDesk}
          running={runningId !== null}
          onUpload={() => setDrawer(drawer === "upload" ? null : "upload")}
        />
      </StateBoundary>
      {sampleWeek && (
        <div className="sample-banner" role="status">
          <strong>Sample week</strong> · These hedges are the seeded example
          week from fixtures, not a live desk run on this week’s markets.
        </div>
      )}
      <div className="intro">
        <div>
          <span className="eyebrow">Your weekly desk</span>
          <h2>A little more certainty.</h2>
          <p>Measured risks. Clear costs. Every decision stays yours.</p>
        </div>
        <div className="intro-actions">
          <span className="badge">No real orders are placed</span>
          <button
            onClick={() => setDrawer(drawer === "chat" ? null : "chat")}
            aria-expanded={drawer === "chat"}
            disabled={isDemo}
          >
            Ask “why?”
          </button>
          <button
            onClick={() => setDrawer(drawer === "settings" ? null : "settings")}
            aria-expanded={drawer === "settings"}
            disabled={isDemo}
          >
            Settings
          </button>
        </div>
      </div>
      {runError && (
        <div role="alert" className="run-error">
          {runError}{" "}
          <button onClick={runDesk} disabled={runningId !== null}>
            Retry run
          </button>
        </div>
      )}
      {isDemo ? (
        <DemoDesk demo={demo} onRemoved={() => select("taxi")} />
      ) : (
        <>
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
                <HedgeList
                  hedges={hedges.data ?? []}
                  onChanged={refresh}
                  exposures={
                    analyze.data
                      ? [...analyze.data.exposures, ...analyze.data.dropped]
                      : []
                  }
                />
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
          <section
            className="panel bottom-panel"
            aria-label="Backtest and books"
            key={`bottom-${selectedId}`}
          >
            <div className="tabs" role="tablist">
              <button
                role="tab"
                id="tab-backtest"
                aria-selected={tab === "backtest"}
                aria-controls="panel-backtest"
                onClick={() => setTab("backtest")}
              >
                Last season, replayed
              </button>
              <button
                role="tab"
                id="tab-ledger"
                aria-selected={tab === "ledger"}
                aria-controls="panel-ledger"
                onClick={() => setTab("ledger")}
              >
                Books &amp; reconciliation
              </button>
            </div>
            {tab === "backtest" ? (
              <div
                role="tabpanel"
                id="panel-backtest"
                aria-labelledby="tab-backtest"
              >
                {errorCode(backtest.error) === "backtest_not_ready" ? (
                  <BacktestNotReady retry={() => backtest.mutate()} />
                ) : (
                  <StateBoundary
                    loading={backtest.isLoading}
                    error={backtest.error}
                    retry={() => backtest.mutate()}
                  >
                    {backtest.data && <BacktestPanel data={backtest.data} />}
                  </StateBoundary>
                )}
              </div>
            ) : (
              <div
                role="tabpanel"
                id="panel-ledger"
                aria-labelledby="tab-ledger"
              >
                <StateBoundary
                  loading={ledger.isLoading}
                  error={ledger.error}
                  retry={() => ledger.mutate()}
                >
                  {ledger.data && (
                    <LedgerTab
                      ledger={ledger.data}
                      businessId={selectedId}
                      benchmark={benchmark.data}
                      onReconciled={() =>
                        Promise.all([ledger.mutate(), decisions.mutate()])
                      }
                    />
                  )}
                </StateBoundary>
              </div>
            )}
          </section>
        </>
      )}
      <ChatDrawer
        key={`chat-${selectedId}`}
        businessId={selectedId}
        open={!isDemo && drawer === "chat"}
        onClose={() => setDrawer(null)}
      />
      <SettingsDrawer
        key={`settings-${selectedId}`}
        businessId={selectedId}
        open={!isDemo && drawer === "settings"}
        onClose={() => setDrawer(null)}
        hedges={hedges.data ?? []}
        onSaved={refreshAfterSettings}
      />
      <DemoUploadDrawer
        open={drawer === "upload"}
        onClose={() => {
          setDrawer(null);
          setQboReturn(null);
        }}
        quickBooksReturn={qboReturn}
        onStart={(upload) => {
          demo.start(upload);
          setDrawer(null);
          select(DEMO_ID);
        }}
      />
      <footer>
        Protection for the business you’re building. · The owner always decides.
      </footer>
    </main>
  );
}
