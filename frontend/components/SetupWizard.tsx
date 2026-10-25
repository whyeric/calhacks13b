"use client";
// First-run setup: business → risks → settings → hedges → dashboard. Reuses
// the dashboard's pieces and #74's scripted upload; no new API calls.
import { useEffect, useState } from "react";
import useSWR from "swr";
import { MOCK_MODE, apiGet, apiPost, apiPut } from "@/lib/api";
import type { Analyze, Business, Hedge, Settings } from "@/lib/types";
import { DEMO_BUDGETS, DEMO_HEDGE, csvSummary } from "@/lib/demoScript";
import { QBO_NAME } from "@/lib/quickbooks";
import { verdictNote } from "@/lib/researchView";
import { fmtUsd } from "@/lib/format";
import { label } from "@/lib/labels";
import { BrandMark } from "./BrandMark";
import { EstimatedBadge } from "./Header";
import { ExposureList } from "./ExposureList";
import { DeclineReasons, HedgeList } from "./HedgeCard";
import { SettingsForm } from "./SettingsDrawer";
import { StateBoundary } from "./StateBoundary";
import {
  DEMO_ID,
  DemoHedgeCard,
  DemoUploadDrawer,
  RESEARCH_MS,
  ResearchTable,
  RunningBar,
  SEND_MS,
  type Demo,
} from "./DemoDesk";

// The bar across from MSG (fixtures: "restaurant").
export const MSG_BAR_ID = "restaurant";
const STEPS = [
  "Your business",
  "Your risks",
  "Your settings",
  "Your hedges",
  "Done",
];
type Choice = "msg" | "upload" | null;

// Ticks every 50 ms until `until` (a Date.now() time), for the progress bars.
function useNow(until: number) {
  const [now, setNow] = useState(() => Date.now());
  const on = now < until;
  useEffect(() => {
    if (!on) return;
    const id = setInterval(() => setNow(Date.now()), 50);
    return () => clearInterval(id);
  }, [on]);
  return now;
}

export function SetupWizard({
  demo,
  onDone,
}: {
  demo: Demo;
  onDone: (businessId: string) => void;
}) {
  const [step, setStep] = useState(1);
  const [choice, setChoice] = useState<Choice>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const businessId = choice === "upload" ? DEMO_ID : MSG_BAR_ID;
  const ready = choice === "msg" || (choice === "upload" && !!demo.upload);
  return (
    <main className="wizard">
      {MOCK_MODE && (
        <div className="mock-banner">MOCK DATA · Demonstration only</div>
      )}
      <header className="wizard-header">
        <div className="brand">
          <BrandMark />
          <div>
            <h1>Offset</h1>
            <p>Steadier weeks. Your call.</p>
          </div>
        </div>
        <p className="wizard-step" aria-live="polite">
          Step {step} of {STEPS.length} · <strong>{STEPS[step - 1]}</strong>
        </p>
      </header>
      <ol className="wizard-progress" aria-label="Setup steps">
        {STEPS.map((name, i) => (
          <li
            key={name}
            className={i + 1 === step ? "current" : i + 1 < step ? "done" : ""}
            aria-current={i + 1 === step ? "step" : undefined}
          >
            {name}
          </li>
        ))}
      </ol>
      <section className="panel wizard-body" aria-label={STEPS[step - 1]}>
        {step === 1 && (
          <BusinessStep
            choice={choice}
            demo={demo}
            onDemo={() => setChoice("msg")}
            onUpload={() => setUploadOpen(true)}
          />
        )}
        {step === 2 &&
          (choice === "upload" ? <UploadRisks demo={demo} /> : <MsgRisks />)}
        {step === 3 &&
          (choice === "upload" ? <UploadSettings /> : <MsgSettings />)}
        {step === 4 &&
          (choice === "upload" ? <UploadHedges demo={demo} /> : <MsgHedges />)}
        {step === 5 && (
          <div>
            <h2>You’re set up</h2>
            <p>
              Your dashboard shows this week’s risks, the protection on offer
              and every decision you make. The desk never approves anything on
              its own; you can re-run setup from the dashboard any time.
            </p>
          </div>
        )}
      </section>
      <nav className="wizard-nav" aria-label="Setup navigation">
        <button onClick={() => setStep(step - 1)} disabled={step === 1}>
          ← Back
        </button>
        {step < STEPS.length ? (
          <button
            className="primary"
            onClick={() => setStep(step + 1)}
            disabled={!ready}
          >
            Next →
          </button>
        ) : (
          <button className="primary" onClick={() => onDone(businessId)}>
            Open my dashboard →
          </button>
        )}
      </nav>
      <DemoUploadDrawer
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onStart={(upload) => {
          demo.start(upload);
          setUploadOpen(false);
          setChoice("upload");
        }}
      />
    </main>
  );
}

// --- Step 1 -------------------------------------------------------------------
function BusinessStep({
  choice,
  demo,
  onDemo,
  onUpload,
}: {
  choice: Choice;
  demo: Demo;
  onDemo: () => void;
  onUpload: () => void;
}) {
  return (
    <div>
      <h2>Which business are we protecting?</h2>
      <p className="muted">
        Add your daily revenue, or look around with the demo bar near Madison
        Square Garden.
      </p>
      <div className="wizard-choices">
        <button
          className={choice === "upload" ? "primary" : ""}
          aria-pressed={choice === "upload"}
          onClick={onUpload}
        >
          Upload your revenue
        </button>
        <button
          className={choice === "msg" ? "primary" : ""}
          aria-pressed={choice === "msg"}
          onClick={onDemo}
        >
          Use demo: bar near MSG
        </button>
        <button disabled title="Coming soon">
          Connect Square / QuickBooks (coming soon)
        </button>
      </div>
      {choice === "upload" && demo.upload && (
        <p role="status" className="wizard-picked">
          <strong>{demo.upload.name}</strong> ·{" "}
          {"csv" in demo.upload ? (
            <>
              {csvSummary(demo.upload.csv)}{" "}
              <span className="badge uploaded">Uploaded · sample</span>
            </>
          ) : (
            QBO_NAME
          )}
        </p>
      )}
      {choice === "msg" && (
        <p role="status" className="wizard-picked">
          <strong>Bar near MSG</strong> · demo business{" "}
          <EstimatedBadge kind="estimated" note="visits × average check" />
        </p>
      )}
    </div>
  );
}

// --- Step 2 -------------------------------------------------------------------
function UploadRisks({ demo }: { demo: Demo }) {
  const elapsed = useNow(demo.startedAt + RESEARCH_MS) - demo.startedAt;
  const result = demo.result;
  if (result && "error" in result)
    return (
      <p role="alert" className="field-error">
        {result.error}
      </p>
    );
  if (!result || elapsed < RESEARCH_MS)
    return (
      <RunningBar
        label="Running analysis…"
        elapsed={elapsed > RESEARCH_MS * 0.95 ? RESEARCH_MS * 0.95 : elapsed}
        total={RESEARCH_MS}
      />
    );
  const report = result.report;
  const declined = report.hypotheses.filter((row) => row.verdict !== "FOUND");
  return (
    <div>
      <h2>What moves your revenue</h2>
      <p className="muted">
        Each risk was tested on 2024 and re-tested on unseen 2025–26 data.
      </p>
      <ResearchTable report={report} sendState={null} />
      <h3>Declined, and why</h3>
      <ul className="wizard-declines">
        {declined.map((row) => (
          <li key={row.id}>
            <strong>{row.label}</strong> ·{" "}
            {verdictNote(row) || "Did not hold up on unseen data."}
          </li>
        ))}
      </ul>
    </div>
  );
}
function MsgRisks() {
  const base = `/businesses/${MSG_BAR_ID}`;
  const analyze = useSWR<Analyze>(["analyze", MSG_BAR_ID], () =>
    apiPost(`${base}/analyze`),
  );
  const hedges = useMsgHedges();
  const declined = (hedges.data ?? []).filter(
    (row) => row.status === "declined",
  );
  return (
    <div>
      <h2>What moves your revenue</h2>
      <StateBoundary
        loading={analyze.isLoading}
        error={analyze.error}
        retry={() => analyze.mutate()}
      >
        {analyze.data && (
          <>
            <h3>Found</h3>
            <ExposureList exposures={analyze.data.exposures} />
            <h3>Declined, and why</h3>
            <ul className="wizard-declines">
              {analyze.data.dropped.map((row) => (
                <li key={row.id}>
                  <strong>{label(row.event)}</strong> · measured, not hedged:{" "}
                  {row.reasons.map(label).join("; ")}
                </li>
              ))}
              {declined.map((row) => (
                <li key={row.id}>
                  <strong>
                    {label(row.exposure_id.replace(/^exp_/, ""))} ·{" "}
                    {row.market_title ?? row.id}
                  </strong>
                  <DeclineReasons hedge={row} />
                </li>
              ))}
            </ul>
            {!analyze.data.dropped.length && !declined.length && (
              <p className="muted">Nothing declined this week.</p>
            )}
          </>
        )}
      </StateBoundary>
    </div>
  );
}

// --- Step 3 -------------------------------------------------------------------
const BUDGET_NOTE =
  "Your weekly budget is your approval line: the desk only proposes protection that fits it, and nothing is bought until you approve.";
function UploadSettings() {
  return (
    <div>
      <h2>Your budget and approval line</h2>
      <p>{BUDGET_NOTE}</p>
      <dl className="budget">
        <div>
          <dt>Weekly budget</dt>
          <dd>{fmtUsd(DEMO_BUDGETS.open.budget)}</dd>
        </div>
      </dl>
      <p className="muted">
        The uploaded sample uses fixed settings. Pick the demo bar to try
        changing them.
      </p>
    </div>
  );
}
function MsgSettings() {
  const path = `/businesses/${MSG_BAR_ID}/settings`;
  const settings = useSWR<Settings>(["settings", MSG_BAR_ID], () =>
    apiGet(path),
  );
  const hedges = useMsgHedges();
  const [saved, setSaved] = useState(false);
  async function save(body: Settings) {
    const next = await apiPut<Settings>(path, body);
    await settings.mutate(next, { revalidate: false });
    await hedges.mutate();
    setSaved(true);
  }
  return (
    <div>
      <h2>Your budget and approval line</h2>
      <p>{BUDGET_NOTE}</p>
      {saved && (
        <p role="status">
          <strong>Saved.</strong> The desk re-checked this week’s hedges.
        </p>
      )}
      <StateBoundary
        loading={settings.isLoading}
        error={settings.error}
        retry={() => settings.mutate()}
      >
        {settings.data && (
          <SettingsForm initial={settings.data} onSave={save} />
        )}
      </StateBoundary>
    </div>
  );
}

// --- Step 4 -------------------------------------------------------------------
const NO_AUTO =
  "Nothing is approved automatically. Approve or reject each proposal yourself, or decide later from the dashboard.";
function useMsgHedges() {
  const businesses = useSWR<Business[]>(["/businesses", "all"], () =>
    apiGet("/businesses"),
  );
  const business = businesses.data?.find((row) => row.id === MSG_BAR_ID);
  // Same key as the dashboard, so its cache carries over.
  return useSWR<Hedge[]>(business ? ["hedges", MSG_BAR_ID] : null, () =>
    apiGet(
      `/businesses/${MSG_BAR_ID}/hedges?week_of=${business!.budget.week_start}`,
    ),
  );
}
function MsgHedges() {
  const hedges = useMsgHedges();
  return (
    <div>
      <p className="wizard-note">{NO_AUTO}</p>
      <StateBoundary
        loading={hedges.isLoading || !hedges.data}
        error={hedges.error}
        retry={() => hedges.mutate()}
      >
        <HedgeList
          hedges={hedges.data ?? []}
          onChanged={() => hedges.mutate()}
        />
      </StateBoundary>
    </div>
  );
}
function UploadHedges({ demo }: { demo: Demo }) {
  const { hedge, upload } = demo;
  const sendStart = hedge?.status === "sending" ? hedge.startedAt : 0;
  const elapsed = useNow(sendStart + SEND_MS) - sendStart;
  if (!upload) return null;
  return (
    <div>
      <h2>This week’s protection</h2>
      <p className="wizard-note">{NO_AUTO}</p>
      {!hedge ? (
        <div>
          <p>
            One risk held up: <strong>{DEMO_HEDGE.title}</strong>. Send it to
            the desk to price protection.
          </p>
          <button className="primary" onClick={demo.send}>
            Send to the desk →
          </button>
        </div>
      ) : hedge.status === "sending" ? (
        <RunningBar
          label="Pricing protection…"
          elapsed={elapsed}
          total={SEND_MS}
        />
      ) : (
        <DemoHedgeCard
          businessName={upload.name}
          status={hedge.status}
          onDecide={demo.decide}
        />
      )}
    </div>
  );
}
