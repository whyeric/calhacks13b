"use client";
// "Upload your revenue": the report is LIVE (POST /research runs the protocol on the uploaded
// CSV; nothing is stored). Connecting QuickBooks Online is the primary path: the backend pulls
// daily income and commitments from the books and runs the same protocol
// (POST /integrations/quickbooks/research), and the same report view renders it. The hedge card after "Send to the desk" is still scripted
// (lib/demoScript.ts, labeled). Client-only business; works in live and mock mode.
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import Link from "next/link";
import type {
  Business,
  CommitmentLine,
  Commitments,
  InventoryLine,
  LogEntry,
  QuickBooksConnect,
  QuickBooksResearch,
  QuickBooksStatus,
  ResearchHypothesis,
  ResearchReport,
} from "@/lib/types";
import {
  DEMO_BUDGETS,
  DEMO_DEFAULTS,
  DEMO_HEDGE,
  DEMO_ID,
  DEMO_KINDS,
  DEMO_SAMPLE,
  PRIVACY_NOTE,
  csvSummary,
  demoBusiness,
  demoLog,
  parseRevenueCsv,
  type DemoHedgeStatus,
  type ParsedCsv,
} from "@/lib/demoScript";
import {
  columnSpan,
  forestAxis,
  position,
  progressPercent,
  tickLabel,
} from "@/lib/chartScale";
import { fmtUsd } from "@/lib/format";
import {
  connectQuickBooks,
  disconnectQuickBooks,
  getQuickBooksStatus,
  postQuickBooksResearch,
  postResearch,
} from "@/lib/api";
import {
  QBO_NAME,
  QBO_RETURN_ERROR,
  byDueDate,
  fmtQty,
  quickBooksErrorText,
  quickBooksSummary,
} from "@/lib/quickbooks";
import {
  ciText,
  daysText,
  estimateText,
  periodLabel,
  placeboText,
  plotOf,
  verdictNote,
} from "@/lib/researchView";
import { Drawer } from "./ChatDrawer";
import { DecisionLog } from "./DecisionLog";

export type CsvUpload = {
  name: string;
  kind: string;
  csv: ParsedCsv;
  text: string;
};
// Connected books: the backend pulls the revenue itself, so there is no file.
export type QuickBooksUpload = {
  name: string;
  kind: string;
  source: "quickbooks";
};
export type DemoUpload = CsvUpload | QuickBooksUpload;
const isQuickBooks = (u: DemoUpload): u is QuickBooksUpload => "source" in u;
type HedgeState = { status: "sending" | DemoHedgeStatus; startedAt: number };
type ResearchState =
  | { report: ResearchReport; quickbooks?: QuickBooksResearch }
  | { error: string };
export type ResearchFn = (csv: string, name: string) => Promise<ResearchReport>;
export type QuickBooksResearchFn = (name: string) => Promise<QuickBooksResearch>;
const liveResearch: ResearchFn = (csv, name) =>
  postResearch<ResearchReport>(csv, name);
const liveQuickBooksResearch: QuickBooksResearchFn = (name) =>
  postQuickBooksResearch<QuickBooksResearch>(name);
// Minimum time the analysis bar stays on screen (the real run is usually faster), and
// how long the (scripted) hedge pricing takes.
export const RESEARCH_MS = 2500;
export const SEND_MS = 2600;

// --- State (lives in the page so switching businesses keeps the demo) -------
export function useDemo(
  research: ResearchFn = liveResearch,
  quickBooksResearch: QuickBooksResearchFn = liveQuickBooksResearch,
) {
  const [upload, setUpload] = useState<DemoUpload | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const [result, setResult] = useState<ResearchState | null>(null);
  const [hedge, setHedge] = useState<HedgeState | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runId = useRef(0);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const start = useCallback(
    (next: DemoUpload) => {
      if (timer.current) clearTimeout(timer.current);
      const id = ++runId.current;
      setUpload(next);
      setStartedAt(Date.now());
      setResult(null);
      setHedge(null);
      setLog([]);
      const run: Promise<ResearchState> = isQuickBooks(next)
        ? quickBooksResearch(next.name).then((quickbooks) => ({
            report: quickbooks.report,
            quickbooks,
          }))
        : research(next.text, next.name).then((report) => ({ report }));
      run.then(
        (state) => {
          if (runId.current === id) setResult(state);
        },
        (err: unknown) => {
          if (runId.current === id)
            setResult({
              error: isQuickBooks(next)
                ? quickBooksErrorText(err, "The analysis failed. Please retry.")
                : err instanceof Error
                  ? err.message
                  : "The analysis failed. Please retry.",
            });
        },
      );
    },
    [research, quickBooksResearch],
  );
  const remove = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    runId.current++;
    setUpload(null);
    setResult(null);
    setHedge(null);
    setLog([]);
  }, []);
  // Tests only: jump to the end of the analysis.
  const skip = useCallback(() => {
    setStartedAt(Date.now() - RESEARCH_MS);
  }, []);
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
    ? isQuickBooks(upload)
      ? {
          ...demoBusiness(upload.name, budget),
          revenue_source: `${QBO_NAME} (researched live, not stored)`,
        }
      : demoBusiness(upload.name, budget)
    : null;
  return {
    upload,
    startedAt,
    result,
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
// --- QuickBooks Online: the primary path ("integrations, not uploads") --------
export type QuickBooksReturn = "connected" | "error" | null;
export function QuickBooksConnectCard({
  open,
  returned = null,
  onPull,
}: {
  open: boolean;
  /** `?qbo=` from the OAuth callback redirect, if the page loaded with one. */
  returned?: QuickBooksReturn;
  onPull: (status: QuickBooksStatus) => void;
}) {
  const [status, setStatus] = useState<QuickBooksStatus | null>(null);
  const [busy, setBusy] = useState<
    "loading" | "connecting" | "redirecting" | "disconnecting" | null
  >(null);
  const [error, setError] = useState("");
  // Fetch the connection each time the drawer opens (also after the OAuth redirect).
  useEffect(() => {
    if (!open) return;
    let live = true;
    setBusy("loading");
    getQuickBooksStatus<QuickBooksStatus>().then(
      (next) => {
        if (!live) return;
        setStatus(next);
        setBusy(null);
      },
      (err: unknown) => {
        if (!live) return;
        setBusy(null);
        // Quiet unless the owner just came back from connecting.
        if (returned === "connected")
          setError(
            quickBooksErrorText(err, "We couldn’t load your QuickBooks connection."),
          );
      },
    );
    return () => {
      live = false;
    };
  }, [open, returned]);
  async function connect() {
    setBusy("connecting");
    setError("");
    try {
      const res = await connectQuickBooks<QuickBooksConnect>();
      if (res.authorize_url) {
        // Live mode: Intuit's consent page; the callback redirects back to /?qbo=…
        setBusy("redirecting");
        window.location.assign(res.authorize_url);
        return;
      }
      setStatus(res.status);
    } catch (err) {
      setError(quickBooksErrorText(err, "QuickBooks didn’t connect. Please retry."));
    }
    setBusy(null);
  }
  async function disconnect() {
    setBusy("disconnecting");
    setError("");
    try {
      setStatus(await disconnectQuickBooks<QuickBooksStatus>());
    } catch (err) {
      setError(quickBooksErrorText(err, "QuickBooks didn’t disconnect. Please retry."));
    }
    setBusy(null);
  }
  const connected = !!status?.connected;
  const shownError =
    error || (returned === "error" && !connected ? QBO_RETURN_ERROR : "");
  return (
    <section
      className="qbo-connect"
      aria-label="QuickBooks Online"
      aria-live="polite"
      data-testid="qbo-connect"
    >
      <div className="row">
        <span className="eyebrow">Connect your books</span>
        {status && (
          <span className="badge" data-testid="qbo-mode">
            {status.mode === "demo" ? "Demo mode" : "Live"}
          </span>
        )}
      </div>
      {connected && status ? (
        <>
          <p className="qbo-company">
            <span className="qbo-dot" aria-hidden="true" />
            <span>
              <strong>{status.company_name ?? "Your QuickBooks company"}</strong>
              <small>
                Connected to {QBO_NAME}
                {status.connected_at && ` · since ${status.connected_at.slice(0, 10)}`}
              </small>
            </span>
          </p>
          {status.synthetic && (
            <p className="badge synthetic" data-testid="qbo-synthetic">
              Synthetic demo data: a fictional company, not real books
            </p>
          )}
          <button
            className="primary"
            type="button"
            disabled={busy !== null}
            onClick={() => onPull(status)}
          >
            Pull revenue and research
          </button>
          <button
            className="link-button"
            type="button"
            disabled={busy !== null}
            onClick={disconnect}
          >
            {busy === "disconnecting" ? "Disconnecting…" : "Disconnect"}
          </button>
        </>
      ) : (
        <>
          <p>
            Connect {QBO_NAME} and the desk reads your daily income, plus what
            you’re already committed to: open purchase orders, unpaid bills,
            pending estimates and inventory. Read-only.
          </p>
          {status?.mode === "demo" && (
            <p className="muted upload-note">
              Demo mode connects a synthetic company (Hudson Bike Co.).
            </p>
          )}
          <button
            className="primary"
            type="button"
            disabled={busy !== null && busy !== "loading"}
            onClick={connect}
          >
            {busy === "connecting"
              ? "Connecting…"
              : busy === "redirecting"
                ? "Opening QuickBooks…"
                : "Connect QuickBooks"}
          </button>
        </>
      )}
      {shownError && (
        <p role="alert" className="field-error">
          {shownError}
        </p>
      )}
    </section>
  );
}

export function DemoUploadDrawer({
  open,
  onClose,
  onStart,
  quickBooksReturn = null,
}: {
  open: boolean;
  onClose: () => void;
  onStart: (upload: DemoUpload) => void;
  quickBooksReturn?: QuickBooksReturn;
}) {
  const [name, setName] = useState(DEMO_DEFAULTS.name);
  const [kind, setKind] = useState(DEMO_DEFAULTS.kind);
  const [fileName, setFileName] = useState("");
  const [csv, setCsv] = useState<ParsedCsv | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  function load(label: string, body: string) {
    const parsed = parseRevenueCsv(body);
    setFileName(label);
    setCsv(parsed);
    setText(body);
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
    onStart({ name: trimmed, kind, csv, text });
  }
  return (
    <Drawer title="Upload your revenue" open={open} onClose={onClose}>
      <p>
        Add your daily revenue and the desk will test which weather and game
        days really move it.
      </p>
      <QuickBooksConnectCard
        open={open}
        returned={quickBooksReturn}
        onPull={(status) =>
          onStart({
            name: status.company_name ?? "QuickBooks company",
            kind,
            source: "quickbooks",
          })
        }
      />
      <p className="eyebrow upload-or">Or upload a CSV</p>
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

// --- Progress -----------------------------------------------------------------
// Uneven pace (fast, stall, catch up) so the bar reads like real work.
const PACE: [number, number][] = [
  [0, 0], [0.1, 0.16], [0.24, 0.27], [0.36, 0.31], [0.52, 0.55],
  [0.66, 0.62], [0.8, 0.79], [0.92, 0.93], [1, 1],
];
function paced(t: number): number {
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  for (let i = 1; i < PACE.length; i++) {
    const [t1, p1] = PACE[i];
    if (t <= t1) {
      const [t0, p0] = PACE[i - 1];
      return p0 + ((t - t0) / (t1 - t0)) * (p1 - p0);
    }
  }
  return 1;
}
function RunningBar({
  label,
  elapsed,
  total,
}: {
  label: string;
  elapsed: number;
  total: number;
}) {
  const pct = progressPercent(paced(total ? elapsed / total : 1));
  return (
    <div className="running" role="status" aria-live="polite">
      <div className="running-label">
        <span className="step-icon spinner" aria-hidden="true" />
        <span>{label}</span>
        <span className="running-pct">{pct}%</span>
      </div>
      <div
        className="demo-progress"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <span style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// --- Report (live) ---------------------------------------------------------------
// Forest plot: $/day effect with 90% interval, training year (grey) over unseen (green).
const FW = 240; // SVG width units
type Axis = ReturnType<typeof forestAxis>;
function Forest({
  row,
  axis,
  labels,
}: {
  row: ResearchHypothesis;
  axis: Axis;
  labels: [string, string];
}) {
  const fx = (value: string) => (position(value, axis.domain) / 100) * FW;
  const line = (plot: [string, string, string], y: number, cls: string) => (
    <g className={cls}>
      <line x1={fx(plot[1])} x2={fx(plot[2])} y1={y} y2={y} className="whisker" />
      <line x1={fx(plot[1])} x2={fx(plot[1])} y1={y - 4} y2={y + 4} className="whisker" />
      <line x1={fx(plot[2])} x2={fx(plot[2])} y1={y - 4} y2={y + 4} className="whisker" />
      <circle cx={fx(plot[0])} cy={y} r={4.5} className="dot" />
    </g>
  );
  const describe = (e: ResearchHypothesis["train"]) =>
    e ? estimateText(e) : "not estimable";
  return (
    <svg
      className="forest"
      viewBox={`0 0 ${FW} 34`}
      role="img"
      aria-label={`${row.label}: ${labels[0]} ${describe(row.train)}; ${labels[1]} ${describe(row.holdout)}`}
    >
      <line x1={fx("0")} x2={fx("0")} y1={0} y2={34} className="zero" />
      {row.train && line(plotOf(row.train), 10, "train")}
      {row.holdout && line(plotOf(row.holdout), 24, "unseen")}
    </svg>
  );
}
function ForestAxis({ axis }: { axis: Axis }) {
  const fx = (value: string) => (position(value, axis.domain) / 100) * FW;
  return (
    <svg className="forest forest-axis" viewBox={`0 0 ${FW} 16`} aria-hidden="true">
      {axis.ticks.map((v) => (
        <text key={v} x={fx(v)} y={11} textAnchor="middle">
          {tickLabel(v)}
        </text>
      ))}
    </svg>
  );
}
function Verdict({ row }: { row: ResearchHypothesis }) {
  const note = verdictNote(row);
  return (
    <span className="verdict">
      <span
        className={`chip ${row.verdict === "FOUND" ? "found" : "not-found"}`}
      >
        {row.verdict}
      </span>
      {note && (
        <span className="verdict-note">
          {row.verdict === "FOUND" ? `· ${note}` : note}
        </span>
      )}
    </span>
  );
}
function EstimateCell({ e }: { e: ResearchHypothesis["train"] }) {
  if (!e)
    return (
      <td>
        <strong>Not estimable</strong>
        <small>too few event days</small>
      </td>
    );
  return (
    <td>
      <strong>{estimateText(e)}</strong>
      <small>{ciText(e)}</small>
      <small>{daysText(e)}</small>
    </td>
  );
}
export function ResearchTable({
  report,
  onSend,
  sendState,
}: {
  report: ResearchReport;
  onSend?: () => void;
  sendState: HedgeState["status"] | null;
}) {
  const train = periodLabel(report.train);
  const unseen = periodLabel(report.holdout);
  const axis = forestAxis(report.plot_max_usd);
  return (
    <div className="research-scroll">
      <table className="demo-research-table">
        <caption className="sr-only">
          Each pre-registered risk, tested on {train} and re-tested on unseen{" "}
          {unseen} data
        </caption>
        <thead>
          <tr>
            <th scope="col">Risk</th>
            <th scope="col">Training year ({train})</th>
            <th scope="col">Unseen ({unseen})</th>
            <th scope="col">
              <span className="sr-only">Effect per day, with 90% CI</span>
              <span className="legend-keys" aria-hidden="true">
                <span className="key train" />
                {train}
                <span className="key unseen" />
                {unseen}
              </span>
              <ForestAxis axis={axis} />
            </th>
            <th scope="col">Placebo</th>
            <th scope="col">Verdict</th>
            <th scope="col">Contract</th>
          </tr>
        </thead>
        <tbody>
          {report.hypotheses.map((row) => (
            <tr key={row.id} data-testid={`research-row-${row.id}`}>
              <th scope="row">
                {row.label}
                <small>{row.mechanism}</small>
              </th>
              <EstimateCell e={row.train} />
              <EstimateCell e={row.holdout} />
              <td className="forest-cell">
                <Forest row={row} axis={axis} labels={[train, unseen]} />
              </td>
              <td>{placeboText(row)}</td>
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
              <td className="kalshi-cell">{row.venue}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Payoff: losses drawn below zero, unhedged (grey) vs hedged net (green) ---
const PAYOFF_DOMAIN: [number, number] = [-2200, 0];
function DemoPayoff() {
  const rows = DEMO_HEDGE.payoff;
  const names = ["It rains", "It stays dry"];
  const W = 320, top = 18, H = 120;
  const zeroY = columnSpan("0", PAYOFF_DOMAIN, top, H).y;
  const bar = (v: string, x: number, cls: string) => {
    const span = columnSpan(v, PAYOFF_DOMAIN, top, H);
    return (
      <g className={cls}>
        <rect x={x} y={span.y} width={56} height={span.height} rx={3} />
        <text x={x + 28} y={span.labelY} textAnchor="middle">
          {fmtUsd(v)}
        </text>
      </g>
    );
  };
  return (
    <div className="payoff">
      <svg className="payoff-svg" viewBox={`0 0 ${W} ${top + H + 40}`} role="img"
        aria-label="Unhedged revenue change vs hedged net, if it rains and if it stays dry">
        <line x1={0} x2={W} y1={zeroY} y2={zeroY} className="zero" />
        <text x={2} y={zeroY - 5} className="axis-note">$0 (a normal day)</text>
        {rows.map((row, i) => {
          const cx = 40 + i * 150;
          return (
            <g key={row.outcome}>
              {bar(row.revenue_vs_base, cx, "unhedged")}
              {bar(row.net_vs_base, cx + 62, "hedged")}
              <text x={cx + 59} y={top + H + 34} textAnchor="middle" className="outcome">
                {names[i]}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="legend">
        <span className="key train" /> Unhedged revenue change
        <span className="key unseen" /> Hedged net, including the premium
      </p>
      <table>
        <caption>Both outcomes, including the premium</caption>
        <thead>
          <tr>
            <th scope="col">Outcome</th>
            <th scope="col">Revenue</th>
            <th scope="col">Payout</th>
            <th scope="col">Premium</th>
            <th scope="col">Net</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.outcome}>
              <th scope="row">{names[i]}</th>
              <td>{fmtUsd(row.revenue_vs_base)}</td>
              <td>{row.contract_payout === "0.00" ? "$0" : `$${row.contract_payout.replace(/\B(?=(\d{3})+(?!\d))/, ",")}`}</td>
              <td>{fmtUsd(row.premium)}</td>
              <td>{fmtUsd(row.net_vs_base)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Hedge card (still SCRIPTED: lib/demoScript.ts DEMO_HEDGE, labeled on the card) ---
// TODO(main): live quote — price the FOUND rain row through the desk (Kalshi + Polymarket)
// instead of DEMO_HEDGE, sized from the report's rain effect.
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
      <p className="badge sample" data-testid="demo-hedge-scripted">
        Example hedge (scripted): not priced from your report yet
      </p>
      <h3>{DEMO_HEDGE.title}</h3>
      <p className="muted">{DEMO_HEDGE.ticker}</p>
      <p className="headline">{DEMO_HEDGE.line}</p>
      <DemoPayoff />
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

// --- "What you're committed to" (QuickBooks): format only; totals come from the API ---
function CommitmentList({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: CommitmentLine[];
  empty: string;
}) {
  return (
    <div className="commitment-list">
      <h4>
        {title} <span className="muted">· {rows.length}</span>
      </h4>
      {rows.length === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        <ul aria-label={title}>
          {byDueDate(rows).map((row) => (
            <li key={row.id} data-testid={`commitment-${row.id}`}>
              <span>
                <strong>{row.counterparty}</strong>
                <small>{row.description}</small>
              </span>
              <span className="commitment-amount">
                <strong>{fmtUsd(row.amount)}</strong>
                <small>
                  {row.due_date ? `due ${row.due_date}` : "no due date"}
                </small>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
function InventoryList({ rows }: { rows: InventoryLine[] }) {
  return (
    <div className="commitment-list">
      <h4>
        Inventory <span className="muted">· {rows.length}</span>
      </h4>
      {rows.length === 0 ? (
        <p className="muted">No inventory tracked.</p>
      ) : (
        <ul aria-label="Inventory">
          {rows.map((row) => (
            <li key={row.id} data-testid={`inventory-${row.id}`}>
              <span>
                <strong>{row.name}</strong>
                <small>
                  {row.sku ? `${row.sku} · ` : ""}
                  {fmtQty(row.qty_on_hand)} on hand × {fmtUsd(row.unit_cost)}
                </small>
              </span>
              <span className="commitment-amount">
                <strong>{fmtUsd(row.value)}</strong>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
export function CommitmentsPanel({ commitments }: { commitments: Commitments }) {
  const c = commitments;
  return (
    <section
      className="commitments"
      aria-label="What you’re committed to"
      data-testid="qbo-commitments"
    >
      <div className="commitments-head">
        <h3>What you’re committed to</h3>
        <span className="muted">
          From {QBO_NAME}, as of {c.as_of}
        </span>
        {c.synthetic && (
          <span className="badge synthetic">Synthetic demo data</span>
        )}
      </div>
      <dl className="commitment-totals">
        <div>
          <dt>Committed spend</dt>
          <dd data-testid="committed-spend">{fmtUsd(c.committed_spend)}</dd>
          <small>Open purchase orders and unpaid bills</small>
        </div>
        <div>
          <dt>Booked future sales</dt>
          <dd data-testid="expected-revenue">{fmtUsd(c.expected_revenue)}</dd>
          <small>Pending estimates</small>
        </div>
        <div>
          <dt>Inventory value</dt>
          <dd data-testid="inventory-value">{fmtUsd(c.inventory_value)}</dd>
          <small>On hand, at cost</small>
        </div>
      </dl>
      <div className="commitment-lists">
        <CommitmentList
          title="Open purchase orders"
          rows={c.purchase_orders}
          empty="No open purchase orders."
        />
        <CommitmentList
          title="Unpaid bills"
          rows={c.bills}
          empty="No unpaid bills."
        />
        <CommitmentList
          title="Pending estimates"
          rows={c.estimates}
          empty="No pending estimates."
        />
        <InventoryList rows={c.inventory} />
      </div>
    </section>
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
  const { upload, startedAt, hedge, result } = demo;
  const total = RESEARCH_MS;
  // Clock: ticks every 50 ms only while something is animating.
  const [now, setNow] = useState(() => Date.now());
  const elapsed = now - startedAt;
  const report = result && "report" in result ? result.report : null;
  const failed = result && "error" in result ? result.error : null;
  const books = result && "quickbooks" in result ? result.quickbooks : undefined;
  const waiting = !result;
  const ticking =
    !!upload &&
    (elapsed < total || waiting || hedge?.status === "sending");
  useEffect(() => {
    if (!ticking) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 50);
    return () => clearInterval(id);
  }, [ticking]);
  if (!upload) return null;
  const researchDone = !!report && elapsed >= total;
  // While the API is still working, the bar holds just short of the end.
  const shown = !report && elapsed > total * 0.95 ? total * 0.95 : elapsed;
  const sendElapsed = hedge ? now - hedge.startedAt : 0;
  return (
    <>
      <section
        className="panel demo-panel"
        aria-label="Research report"
        data-testid="demo-research"
      >
        <div className="section-heading">
          <div>
            <span className="eyebrow">Research my risks</span>
            <h2>
              {upload.name} ·{" "}
              {isQuickBooks(upload)
                ? books
                  ? quickBooksSummary(books)
                  : QBO_NAME
                : csvSummary(upload.csv)}
            </h2>
            {books && (
              <p className="qbo-source" data-testid="qbo-source">
                {books.synthetic && (
                  <span className="badge synthetic">Synthetic demo data</span>
                )}{" "}
                Revenue: {books.revenue_source}
              </p>
            )}
          </div>
          <div className="demo-actions">
            <button
              onClick={() => {
                demo.remove();
                onRemoved();
              }}
            >
              {isQuickBooks(upload) ? "Clear report" : "Remove upload"}
            </button>
          </div>
        </div>
        {failed && (
          <p role="alert" className="field-error">
            {failed}
          </p>
        )}
        {!failed && !researchDone && (
          <RunningBar label="Running analysis…" elapsed={shown} total={total} />
        )}
        {report && researchDone && (
          <div className="demo-report">
            {report.notes.length > 0 && (
              <p className="badge sample" data-testid="research-file-notes">
                From your {books ? "books" : "file"}: {report.notes.join(" ")}
              </p>
            )}
            <p className="demo-summary">{report.summary}</p>
            <ul className="protocol-chips" aria-label="Protocol">
              {report.protocol.map((chip) => (
                <li key={chip} className="badge">
                  {chip}
                </li>
              ))}
            </ul>
            <ResearchTable
              report={report}
              onSend={demo.send}
              sendState={hedge?.status ?? null}
            />
            <p className="muted demo-footnote">
              Computed live on your {books ? "QuickBooks revenue" : "file"}{" "}
              against {report.station}:{" "}
              {report.n_days.toLocaleString("en-US")} days used
              {report.n_closed_days > 0 &&
                `, ${report.n_closed_days.toLocaleString("en-US")} zero-revenue days left out`}
              {report.n_outside_window > 0 &&
                `, ${report.n_outside_window.toLocaleString("en-US")} days outside the weather record`}
              . Effects are $ per day at each period’s average. FOUND means the{" "}
              {periodLabel(report.train)} effect is clear of zero after
              correcting for {report.hypotheses.length} tests, holds the same
              sign on unseen {periodLabel(report.holdout)} data, and the 7-day
              placebo shows nothing.{" "}
              <Link href="/research">How this works</Link>
            </p>
            {books && <CommitmentsPanel commitments={books.commitments} />}
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
              <RunningBar label="Pricing protection…" elapsed={sendElapsed} total={SEND_MS} />
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
