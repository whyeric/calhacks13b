"use client";
// Scripted "Upload your revenue" demo: client-only, works in live and mock
// mode. All figures come from lib/demoScript.ts (hardcoded strings).
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import Link from "next/link";
import type { Business, LogEntry } from "@/lib/types";
import {
  DEMO_BUDGETS,
  DEMO_DEFAULTS,
  DEMO_HEDGE,
  DEMO_ID,
  DEMO_KINDS,
  DEMO_SAMPLE,
  FOREST_DOMAIN,
  HYPOTHESES,
  HYPOTHESIS_PAUSE_MS,
  PRIVACY_NOTE,
  PROTOCOL_CHIPS,
  RESEARCH_ROWS,
  SEND_STEPS,
  SUMMARY,
  TYPE_MS,
  csvSummary,
  demoBusiness,
  demoLog,
  parseRevenueCsv,
  researchSteps,
  type DemoHedgeStatus,
  type ParsedCsv,
  type ResearchRow,
  type Step,
} from "@/lib/demoScript";
import { intervalSpan, position } from "@/lib/chartScale";
import { Drawer } from "./ChatDrawer";
import { PayoffChart } from "./HedgeCard";
import { DecisionLog } from "./DecisionLog";

export type DemoUpload = { name: string; kind: string; csv: ParsedCsv };
type HedgeState = { status: "sending" | DemoHedgeStatus; startedAt: number };
const totalMs = (steps: Step[]) =>
  steps.reduce((sum, step) => sum + step.ms, 0);
const SEND_MS = totalMs(SEND_STEPS);

// --- State (lives in the page so switching businesses keeps the demo) -------
export function useDemo() {
  const [upload, setUpload] = useState<DemoUpload | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const [hedge, setHedge] = useState<HedgeState | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const start = useCallback((next: DemoUpload) => {
    if (timer.current) clearTimeout(timer.current);
    setUpload(next);
    setStartedAt(Date.now());
    setHedge(null);
    setLog([]);
  }, []);
  const remove = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    setUpload(null);
    setHedge(null);
    setLog([]);
  }, []);
  const skip = useCallback(() => {
    if (upload)
      setStartedAt(
        Date.now() - totalMs(researchSteps(upload.csv.rows, upload.kind)),
      );
  }, [upload]);
  const send = useCallback(() => {
    if (!upload) return;
    setHedge({ status: "sending", startedAt: Date.now() });
    timer.current = setTimeout(() => {
      setHedge({ status: "proposed", startedAt: Date.now() });
      setLog((rows) => [...rows, demoLog("proposal", upload.name)]);
    }, SEND_MS);
  }, [upload]);
  const decide = useCallback(
    (approved: boolean) => {
      if (!upload) return;
      setHedge({
        status: approved ? "approved" : "rejected",
        startedAt: Date.now(),
      });
      setLog((rows) => [
        ...rows,
        demoLog(approved ? "approval" : "rejection", upload.name),
      ]);
    },
    [upload],
  );
  const budget =
    hedge?.status === "proposed"
      ? DEMO_BUDGETS.pending
      : hedge?.status === "approved"
        ? DEMO_BUDGETS.approved
        : DEMO_BUDGETS.open;
  const business: Business | null = upload
    ? demoBusiness(upload.name, budget)
    : null;
  return {
    upload,
    startedAt,
    hedge,
    log,
    business,
    start,
    remove,
    skip,
    send,
    decide,
  };
}
export type Demo = ReturnType<typeof useDemo>;

// --- Upload drawer -----------------------------------------------------------
async function readText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}
export function DemoUploadDrawer({
  open,
  onClose,
  onStart,
}: {
  open: boolean;
  onClose: () => void;
  onStart: (upload: DemoUpload) => void;
}) {
  const [name, setName] = useState(DEMO_DEFAULTS.name);
  const [kind, setKind] = useState(DEMO_DEFAULTS.kind);
  const [fileName, setFileName] = useState("");
  const [csv, setCsv] = useState<ParsedCsv | null>(null);
  const [error, setError] = useState("");
  function load(label: string, text: string) {
    const parsed = parseRevenueCsv(text);
    setFileName(label);
    setCsv(parsed);
    setError(
      parsed
        ? ""
        : "We couldn't find any dated rows. The file needs a date,revenue header and one row per day.",
    );
  }
  async function pick(file: File | undefined) {
    if (!file) return;
    try {
      load(file.name, await readText(file));
    } catch {
      setError("We couldn't read that file.");
    }
  }
  async function loadSample() {
    try {
      const res = await fetch(DEMO_SAMPLE.href);
      if (!res.ok) throw new Error();
      load(DEMO_SAMPLE.file, await res.text());
    } catch {
      setError("The sample file is unavailable. Download it and pick it.");
    }
  }
  const trimmed = name.trim();
  const ready = !!trimmed && trimmed.length <= 60 && !!csv;
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || !csv) return;
    onStart({ name: trimmed, kind, csv });
  }
  return (
    <Drawer title="Upload your revenue" open={open} onClose={onClose}>
      <p>
        Add your daily revenue and the desk will test which weather and game
        days really move it.
      </p>
      <form className="upload-form" onSubmit={submit}>
        <label htmlFor="upload-name">Business name</label>
        <input
          id="upload-name"
          value={name}
          maxLength={60}
          onChange={(e) => setName(e.target.value)}
        />
        <label htmlFor="upload-kind">Type</label>
        <select
          id="upload-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          {DEMO_KINDS.map((row) => (
            <option key={row}>{row}</option>
          ))}
        </select>
        <label htmlFor="upload-file">Daily revenue (CSV)</label>
        <input
          id="upload-file"
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => pick(e.target.files?.[0])}
        />
        {csv && (
          <p className="upload-parsed" role="status">
            <strong>{fileName}</strong> · {csvSummary(csv)}
          </p>
        )}
        {error && (
          <p role="alert" className="field-error">
            {error}
          </p>
        )}
        <p className="muted upload-note">
          Two columns, one row per day: <code>date,revenue</code>. Lines
          starting with <code>#</code> are ignored. About a year and a half of
          history or more works best.
        </p>
        <p className="upload-privacy">{PRIVACY_NOTE}</p>
        <button className="primary" type="submit" disabled={!ready}>
          Upload and research
        </button>
      </form>
      <div className="upload-samples">
        <p className="eyebrow">No file handy?</p>
        <p>
          <a href={DEMO_SAMPLE.href} download={DEMO_SAMPLE.file}>
            Download {DEMO_SAMPLE.title}
          </a>
        </p>
        <button type="button" onClick={loadSample}>
          Use the sample file
        </button>
      </div>
    </Drawer>
  );
}

// --- Staged progress ----------------------------------------------------------
function StepIcon({ state }: { state: "done" | "active" | "waiting" }) {
  if (state === "done")
    return (
      <span className="step-icon done" aria-label="done">
        ✓
      </span>
    );
  if (state === "active")
    return <span className="step-icon spinner" aria-label="working" />;
  return <span className="step-icon waiting" aria-hidden="true" />;
}
export function StepList({
  steps,
  elapsed,
  children,
}: {
  steps: Step[];
  elapsed: number;
  children?: (step: Step, local: number) => React.ReactNode;
}) {
  let offset = 0;
  const all = totalMs(steps);
  const shown = steps.map((step) => {
    const begin = offset;
    offset += step.ms;
    return { step, begin };
  });
  return (
    <ol className="demo-steps">
      {shown
        .filter(({ begin }) => begin <= elapsed)
        .map(({ step, begin }) => {
          const finished =
            elapsed >= begin + step.ms && (step.ms > 0 || elapsed >= all);
          return (
            <li key={step.id} className={finished ? "is-done" : "is-active"}>
              <StepIcon state={finished ? "done" : "active"} />
              <div>
                <span>{step.text}</span>
                {children?.(step, elapsed - begin)}
              </div>
            </li>
          );
        })}
    </ol>
  );
}
// Pre-registered mechanisms, typed one by one during the "claude" step.
function Typewriter({ local }: { local: number }) {
  let offset = 400;
  return (
    <ul className="typed-hypotheses">
      {HYPOTHESES.map((row) => {
        const begin = offset;
        offset += row.mechanism.length * TYPE_MS + HYPOTHESIS_PAUSE_MS;
        if (local < begin) return null;
        const typed = ((local - begin) / TYPE_MS) | 0;
        const text = row.mechanism.slice(0, typed);
        const typing = typed < row.mechanism.length;
        return (
          <li key={row.label}>
            <strong>{row.label}:</strong> “{text}
            {typing ? <span className="caret" aria-hidden="true" /> : "”"}
          </li>
        );
      })}
    </ul>
  );
}
function ProgressBar({ elapsed, total }: { elapsed: number; total: number }) {
  const pct = total ? (elapsed >= total ? 100 : (elapsed / total) * 100) : 100;
  return (
    <div
      className="demo-progress"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct | 0}
    >
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

// --- Report --------------------------------------------------------------------
function Forest({ row }: { row: ResearchRow }) {
  const zero = position("0", FOREST_DOMAIN);
  const bar = (
    plot: string[] | null,
    cls: "train" | "unseen",
    title: string,
  ) => {
    if (!plot) return null;
    const point = position(plot[0], FOREST_DOMAIN);
    const ci =
      plot.length === 3 ? intervalSpan(plot[1], plot[2], FOREST_DOMAIN) : null;
    return (
      <span className={`forest-row ${cls}`} title={title}>
        {ci && (
          <span
            className="forest-ci"
            style={{ left: `${ci.x}%`, width: `${ci.width}%` }}
          />
        )}
        <span className="forest-point" style={{ left: `${point}%` }} />
      </span>
    );
  };
  return (
    <div
      className="forest"
      role="img"
      aria-label={`${row.label}: training ${row.train.text}; unseen ${row.unseen.text}`}
    >
      <span className="forest-zero" style={{ left: `${zero}%` }} />
      {bar(row.train.plot, "train", `Training year: ${row.train.text}`)}
      {bar(row.unseen.plot, "unseen", `Unseen: ${row.unseen.text}`)}
    </div>
  );
}
function Verdict({ row }: { row: ResearchRow }) {
  return (
    <span className="verdict">
      <span
        className={`chip ${row.verdict === "FOUND" ? "found" : "not-found"}`}
      >
        {row.verdict}
      </span>
      {row.verdictNote && (
        <span className="verdict-note">
          {row.verdict === "FOUND" ? `· ${row.verdictNote}` : row.verdictNote}
        </span>
      )}
    </span>
  );
}
export function ResearchTable({
  onSend,
  sendState,
}: {
  onSend?: () => void;
  sendState: HedgeState["status"] | null;
}) {
  return (
    <div className="research-scroll">
      <table className="demo-research-table">
        <caption className="sr-only">
          Each pre-registered risk, tested on 2024 and re-tested on unseen
          2025–26 data
        </caption>
        <thead>
          <tr>
            <th scope="col">Risk</th>
            <th scope="col">Training year (2024)</th>
            <th scope="col">Unseen (2025–26)</th>
            <th scope="col">
              <span className="sr-only">Effect per day, with 90% CI</span>
              <span className="legend-keys" aria-hidden="true">
                <span className="key train" />
                2024
                <span className="key unseen" />
                2025–26
              </span>
            </th>
            <th scope="col">Placebo</th>
            <th scope="col">Verdict</th>
            <th scope="col">Kalshi</th>
          </tr>
        </thead>
        <tbody>
          {RESEARCH_ROWS.map((row) => (
            <tr key={row.id} data-testid={`research-row-${row.id}`}>
              <th scope="row">
                {row.label}
                <small>{row.mechanism}</small>
              </th>
              <td>
                <strong>{row.train.text}</strong>
                <small>{row.train.ci}</small>
                <small>{row.train.days}</small>
              </td>
              <td>
                <strong>{row.unseen.text}</strong>
                {row.unseen.ci && <small>{row.unseen.ci}</small>}
                {row.unseen.days && <small>{row.unseen.days}</small>}
              </td>
              <td className="forest-cell">
                <Forest row={row} />
              </td>
              <td>{row.placebo}</td>
              <td>
                <Verdict row={row} />
                {row.sendable && onSend && (
                  <button
                    className="primary send-desk"
                    onClick={onSend}
                    disabled={sendState !== null}
                  >
                    {sendState === null
                      ? "Send to the desk →"
                      : sendState === "sending"
                        ? "Sending…"
                        : "Sent to the desk"}
                  </button>
                )}
              </td>
              <td className="kalshi-cell">{row.kalshi}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Hedge card -------------------------------------------------------------
const STATUS_TEXT: Record<DemoHedgeStatus, string> = {
  proposed: "Proposed · only you can approve",
  approved: "Approved by you",
  rejected: "Rejected by you",
};
export function DemoHedgeCard({
  businessName,
  status,
  onDecide,
}: {
  businessName: string;
  status: DemoHedgeStatus;
  onDecide: (approved: boolean) => void;
}) {
  return (
    <article className="hedge-card demo-hedge" data-testid="demo-hedge-card">
      <div className="row">
        <span className="eyebrow">Rain protection · {businessName}</span>
        <span className={`chip ${status}`}>{STATUS_TEXT[status]}</span>
      </div>
      <h3>{DEMO_HEDGE.title}</h3>
      <p className="muted">{DEMO_HEDGE.ticker}</p>
      <p className="headline">{DEMO_HEDGE.line}</p>
      <PayoffChart rows={DEMO_HEDGE.payoff} event="rain" />
      <p>{DEMO_HEDGE.expectedCost}</p>
      <ul className="checks demo-checks">
        {DEMO_HEDGE.checks.map((check) => (
          <li key={check}>
            <strong>{check}</strong> · Pass
          </li>
        ))}
      </ul>
      {status === "proposed" && (
        <div className="approve-bar">
          <div className="row">
            <p>Only you can approve protection.</p>
            <div className="actions">
              <button onClick={() => onDecide(false)}>Reject</button>
              <button className="primary" onClick={() => onDecide(true)}>
                Approve
              </button>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}

// --- The demo business view -------------------------------------------------
export function DemoDesk({
  demo,
  onRemoved,
}: {
  demo: Demo;
  onRemoved: () => void;
}) {
  const { upload, startedAt, hedge } = demo;
  const steps = upload ? researchSteps(upload.csv.rows, upload.kind) : [];
  const total = totalMs(steps);
  // Clock: ticks every 50 ms only while something is animating.
  const [now, setNow] = useState(() => Date.now());
  const elapsed = now - startedAt;
  const ticking = !!upload && (elapsed < total || hedge?.status === "sending");
  useEffect(() => {
    if (!ticking) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 50);
    return () => clearInterval(id);
  }, [ticking]);
  if (!upload) return null;
  const researchDone = elapsed >= total;
  const sendElapsed = hedge ? now - hedge.startedAt : 0;
  return (
    <>
      <section
        className="panel demo-panel"
        aria-label="Research report"
        data-testid="demo-research"
      >
        <span className="scripted-label">Scripted demo</span>
        <div className="section-heading">
          <div>
            <span className="eyebrow">Research my risks</span>
            <h2>
              {upload.name} · {csvSummary(upload.csv)}
            </h2>
          </div>
          <div className="demo-actions">
            {!researchDone && (
              <button onClick={demo.skip}>Skip animation</button>
            )}
            <button
              onClick={() => {
                demo.remove();
                onRemoved();
              }}
            >
              Remove upload
            </button>
          </div>
        </div>
        <ProgressBar elapsed={elapsed} total={total} />
        <StepList steps={steps} elapsed={elapsed}>
          {(step, local) =>
            step.id === "claude" ? <Typewriter local={local} /> : null
          }
        </StepList>
        {researchDone && (
          <div className="demo-report">
            <p className="demo-summary">{SUMMARY}</p>
            <ul className="protocol-chips" aria-label="Protocol">
              {PROTOCOL_CHIPS.map((chip) => (
                <li key={chip} className="badge">
                  {chip}
                </li>
              ))}
            </ul>
            <ResearchTable
              onSend={demo.send}
              sendState={hedge?.status ?? null}
            />
            <p className="muted demo-footnote">
              Effects are $ per day at the training-year average. FOUND means
              the 2024 effect is clear of zero after correcting for 6 tests,
              holds the same sign on unseen 2025–26 data, and the 7-day placebo
              shows nothing. <Link href="/research">How this works</Link>
            </p>
          </div>
        )}
      </section>
      <div className="demo-grid">
        <section className="hedges-panel" aria-label="Hedge decisions">
          <div className="section-heading">
            <h2>This week’s protection</h2>
          </div>
          {hedge?.status === "sending" ? (
            <div className="panel">
              <ProgressBar elapsed={sendElapsed} total={SEND_MS} />
              <StepList steps={SEND_STEPS} elapsed={sendElapsed} />
            </div>
          ) : hedge ? (
            <DemoHedgeCard
              businessName={upload.name}
              status={hedge.status}
              onDecide={demo.decide}
            />
          ) : (
            <p className="state">
              Nothing proposed yet. Send a risk that holds up to the desk.
            </p>
          )}
        </section>
        <section className="panel log-panel" aria-label="Decision log">
          <div className="section-heading">
            <h2>Decision log</h2>
            <span className="live-dot" aria-hidden="true" />
          </div>
          <p className="muted">Every decision has a receipt.</p>
          <DecisionLog decisions={demo.log} />
        </section>
      </div>
    </>
  );
}
export { DEMO_ID };
