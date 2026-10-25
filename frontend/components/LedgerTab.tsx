"use client";
import { useState } from "react";
import type {
  Ledger,
  LedgerEntry,
  ReconBenchmark,
  Reconciliation,
} from "@/lib/types";
import { fmtUsd } from "@/lib/format";
import { label } from "@/lib/labels";
import { apiPost } from "@/lib/api";
import { EstimatedBadge } from "./Header";
import { weekLabel } from "./BacktestPanel";

const SIMULATED_NOTE =
  "settlements and the bank statement are simulated from real market results";

const KINDS: Record<LedgerEntry["kind"], string> = {
  premium: "Premium paid",
  payout: "Payout received",
  withdrawal: "Withdrawal to bank",
  opening_deposit: "Opening deposit",
};
// Where each leg of the three-way check came from (I6: anything not live is labeled).
const VENUE_ORIGIN: Record<string, string> = {
  simulated: "simulated",
  kalshi_demo: "Kalshi demo",
  kalshi_live: "Kalshi",
};
const BANK_ORIGIN: Record<string, string> = {
  csv_simulated: "simulated",
  increase_sandbox: "Increase sandbox",
  increase_live: "Increase",
};
const RECORD: Record<string, string> = {
  venue: "the venue",
  ledger: "our ledger",
  bank: "the bank",
};
function EntryRow({ entry }: { entry: LedgerEntry }) {
  return (
    <tr className={entry.simulated ? "simulated-row" : ""}>
      <th scope="row">{weekLabel(entry.date)}</th>
      <td className="text-left">
        {KINDS[entry.kind] ?? label(entry.kind)}
        <small className="narration">{entry.narration}</small>
      </td>
      <td className="text-left">
        <ul className="postings">
          {entry.postings.map((posting) => (
            <li key={posting.account}>
              <span>{posting.account}</span>{" "}
              <span>{fmtUsd(posting.amount)}</span>
            </li>
          ))}
        </ul>
      </td>
      <td>
        {entry.simulated ? (
          <span className="badge simulated">Simulated</span>
        ) : (
          <span className="badge">Booked on approval</span>
        )}
      </td>
    </tr>
  );
}
export function ReconcilePanel({
  reconciliation,
  businessId,
  onReconciled,
}: {
  reconciliation: Reconciliation | null;
  businessId: string;
  onReconciled: () => Promise<unknown>;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function run() {
    setPending(true);
    setError("");
    try {
      await apiPost(`/businesses/${encodeURIComponent(businessId)}/reconcile`);
      await onReconciled();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Reconciliation failed. Retry.",
      );
    } finally {
      setPending(false);
    }
  }
  const sources = reconciliation?.sources ?? null;
  const venueOrigin = VENUE_ORIGIN[sources?.venue_origin ?? "simulated"];
  const bankOrigin = BANK_ORIGIN[sources?.bank_origin ?? "csv_simulated"];
  const inTransit = reconciliation?.in_transit ?? [];
  return (
    <section className="reconcile" aria-label="Reconciliation">
      <div className="section-heading">
        <h3>Three-way check</h3>
        {reconciliation?.simulated !== false && (
          <EstimatedBadge kind="simulated" note="bank statement" />
        )}
        <button onClick={run} disabled={pending}>
          {pending ? "Checking…" : "Run reconciliation"}
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {!reconciliation ? (
        <p className="muted">
          Not reconciled yet. Run it to compare what we expected, the Kalshi
          ledger and the bank.
        </p>
      ) : (
        <>
          <p className="muted">
            As of {weekLabel(reconciliation.as_of)} ·{" "}
            {reconciliation.summary.n_matched} matched ·{" "}
            {reconciliation.summary.n_mismatched} flagged
            {inTransit.length > 0 && <> · {inTransit.length} in transit</>}
            {reconciliation.summary.n_mismatched > 0 && (
              <> · off by {fmtUsd(reconciliation.summary.total_difference)}</>
            )}
          </p>
          <table>
            <caption>
              What the venue paid vs. what we booked vs. what the bank received,
              per payout
            </caption>
            <thead>
              <tr>
                <th scope="col">Payout</th>
                <th scope="col">Expected</th>
                <th scope="col">Venue ({venueOrigin})</th>
                <th scope="col">Kalshi ledger</th>
                <th scope="col">Bank ({bankOrigin})</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {reconciliation.matches.map((row) => (
                <tr key={row.hedge_id}>
                  <th scope="row">{row.ticker}</th>
                  <td>{fmtUsd(row.expected)}</td>
                  <td>{row.venue == null ? "—" : fmtUsd(row.venue)}</td>
                  <td>{fmtUsd(row.kalshi_ledger)}</td>
                  <td>{fmtUsd(row.bank)}</td>
                  <td>✓ Matches</td>
                </tr>
              ))}
              {reconciliation.mismatches.map((row) => (
                <tr
                  key={row.hedge_id}
                  className="mismatch"
                  data-testid="mismatch-row"
                >
                  <th scope="row">{row.ticker}</th>
                  <td>{fmtUsd(row.expected)}</td>
                  <td>{row.venue == null ? "—" : fmtUsd(row.venue)}</td>
                  <td>{fmtUsd(row.kalshi_ledger)}</td>
                  <td>{fmtUsd(row.bank)}</td>
                  <td>
                    <strong>⚠ Flagged · {fmtUsd(row.difference)}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {reconciliation.mismatches.map((row) => (
            <div
              key={row.hedge_id}
              className="mismatch-note"
              role="note"
              aria-label={`Flagged payout ${row.ticker}`}
            >
              <p>
                <strong>⚠ {row.ticker}:</strong> {row.explanation}
              </p>
              {row.system_of_record && (
                <p className="record-of-truth" data-testid="record-of-truth">
                  <strong>Trusted: {RECORD[row.system_of_record]}.</strong>{" "}
                  {row.record_reason}
                </p>
              )}
              {row.action === "ask_owner" && (
                <p className="owner-question">
                  <strong>Question for you:</strong> {row.question}
                </p>
              )}
            </div>
          ))}
          {inTransit.length > 0 && (
            <div className="in-transit" data-testid="in-transit">
              <h4>In transit: timing, not an error</h4>
              <ul>
                {inTransit.map((row) => (
                  <li key={row.hedge_id}>
                    <strong>{row.ticker}:</strong> {row.explanation}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {(sources?.notes ?? []).length > 0 && (
            <ul
              className="muted source-notes"
              aria-label="Where each record came from"
            >
              {sources!.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
const CAUSES: Record<string, string> = {
  fee_deducted_from_deposit: "Fee netted from deposit",
  duplicate_deposit: "Duplicate deposit",
  transposed_digits: "Transposed digits",
  reversed_sign: "Reversed sign",
  missing_deposit: "Missing deposit",
  ledger_payout_differs: "Ledger payout wrong",
  deposit_amount_differs: "Deposit amount differs",
  unexplained_bank_row: "Unexplained bank row",
  venue_paid_differs_from_booked: "Venue paid ≠ booked",
  result_differs_from_venue: "Result differs from venue",
  fee_differs_from_venue: "Fee differs from venue",
  venue_record_missing: "No venue settlement",
  unbooked_venue_settlement: "Unbooked venue settlement",
};
const cause = (code: string | null) =>
  code === null ? "Not flagged" : (CAUSES[code] ?? label(code));

// The reconciler scored on a simulated world with planted errors and an answer key
// (GET /benchmarks/reconciliation). Counts and verdicts come from the API as is.
export function BenchmarkScorecard({
  benchmark,
}: {
  benchmark: ReconBenchmark;
}) {
  return (
    <section
      className="benchmark"
      aria-label="Planted-error benchmark"
      data-testid="recon-benchmark"
    >
      <div className="section-heading">
        <h3>Planted-error benchmark</h3>
        <EstimatedBadge kind="simulated" note="planted errors, answer key" />
      </div>
      <p>
        <strong>
          Caught {benchmark.n_caught} of {benchmark.n_planted}
        </strong>{" "}
        planted errors · {benchmark.n_cause_correct} with the right cause ·{" "}
        {benchmark.n_false_flags} false flags on {benchmark.n_traps} traps
      </p>
      <details>
        <summary>
          Show the answer key ({benchmark.cases.length} cases,{" "}
          {benchmark.n_hedges} simulated hedges)
        </summary>
        <table>
          <caption>Planted cause vs. what the reconciler found</caption>
          <thead>
            <tr>
              <th scope="col" className="text-left">
                Case
              </th>
              <th scope="col" className="text-left">
                Planted
              </th>
              <th scope="col" className="text-left">
                Found
              </th>
              <th scope="col">Result</th>
            </tr>
          </thead>
          <tbody>
            {benchmark.cases.map((row) => (
              <tr key={row.subject} data-testid="benchmark-case">
                <th scope="row" className="text-left">
                  {row.subject}
                  <small className="narration">{row.description}</small>
                </th>
                <td className="text-left">
                  {row.kind === "trap"
                    ? "Trap (looks odd, is fine)"
                    : cause(row.expected_cause ?? null)}
                </td>
                <td className="text-left">{cause(row.found_cause ?? null)}</td>
                <td>{row.correct ? "✓" : "✗"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {benchmark.false_flags.length > 0 && (
          <p role="note">False flags: {benchmark.false_flags.join(", ")}</p>
        )}
      </details>
    </section>
  );
}
export function LedgerTab({
  ledger,
  businessId,
  onReconciled,
  benchmark,
}: {
  ledger: Ledger;
  businessId: string;
  onReconciled: () => Promise<unknown>;
  benchmark?: ReconBenchmark;
}) {
  return (
    <div className="ledger" data-testid="ledger-tab">
      <div className="row">
        <p className="muted">
          Every approved hedge is booked here. No real orders are placed.
        </p>
        {ledger.simulated && (
          <EstimatedBadge kind="simulated" note={SIMULATED_NOTE} />
        )}
      </div>
      <div className="ledger-grid">
        <section aria-label="Ledger entries">
          <h3>Ledger</h3>
          {ledger.entries.length ? (
            <table>
              <caption>Entries, oldest first</caption>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col" className="text-left">
                    What
                  </th>
                  <th scope="col" className="text-left">
                    Postings
                  </th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {ledger.entries.map((entry) => (
                  <EntryRow key={entry.id} entry={entry} />
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No ledger entries yet. Approve a hedge.</p>
          )}
        </section>
        <ReconcilePanel
          reconciliation={ledger.reconciliation}
          businessId={businessId}
          onReconciled={onReconciled}
        />
      </div>
      {benchmark && <BenchmarkScorecard benchmark={benchmark} />}
    </div>
  );
}
