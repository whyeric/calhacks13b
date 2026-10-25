"use client";
import { useState } from "react";
import type { ExposureRow, Hedge, HedgeLeg } from "@/lib/types";
import { fmtCents, fmtUsd } from "@/lib/format";
import { label } from "@/lib/labels";
import { apiPost } from "@/lib/api";
import { EstimatedBadge } from "./Header";

const TEAMS: Record<string, string> = {
  NYK: "Knicks",
  NYR: "Rangers",
  CHC: "Cubs",
  GSW: "Warriors",
};
// Contract counts are integers from the API; grouping only.
const count = (n: number) => n.toLocaleString("en-US");
// Team nickname from the ticker suffix (KXNBA-27-NYK → Knicks); display only.
export function teamName(legs: Hedge[]): string {
  for (const leg of legs) {
    const code = leg.ticker?.split("-").at(-1);
    if (code && TEAMS[code]) return TEAMS[code];
  }
  return "home team";
}
// Playoff legs share one exposure_id and are one decision for the owner.
export const isSeasonLeg = (hedge: Hedge) => /playoff/.test(hedge.exposure_id);

// Hedges in API order, with every playoff leg collected at the first leg's slot.
export function groupHedges(hedges: Hedge[]): (Hedge | Hedge[])[] {
  const seen = new Map<string, Hedge[]>();
  const out: (Hedge | Hedge[])[] = [];
  for (const row of hedges) {
    if (!isSeasonLeg(row)) {
      out.push(row);
      continue;
    }
    const set = seen.get(row.exposure_id);
    if (set) set.push(row);
    else {
      const next = [row];
      seen.set(row.exposure_id, next);
      out.push(next);
    }
  }
  return out;
}

function GroupApprove({
  legs,
  onChanged,
}: {
  legs: Hedge[];
  onChanged: () => Promise<unknown>;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const open = legs.filter((leg) =>
    ["proposed", "pending_approval"].includes(leg.status),
  );
  if (!open.length) return null;
  async function decide(action: "approve" | "reject") {
    setPending(true);
    setError("");
    try {
      for (const leg of open)
        await apiPost(`/hedges/${encodeURIComponent(leg.id)}/${action}`, {
          actor: "owner",
        });
      await onChanged();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Decision failed. Please try again.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="approve-bar">
      <div className="row">
        <p>Only you can approve protection. This decides every leg.</p>
        <div className="actions">
          <button disabled={pending} onClick={() => decide("reject")}>
            Reject all
          </button>
          <button
            className="primary"
            disabled={pending}
            onClick={() => decide("approve")}
          >
            {pending ? "Saving…" : "Approve all"}
          </button>
        </div>
      </div>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}

export function PlayoffCard({
  legs,
  exposure,
  onChanged,
}: {
  legs: Hedge[];
  exposure?: ExposureRow;
  onChanged: () => Promise<unknown>;
}) {
  const rows = legs as HedgeLeg[];
  const team = teamName(legs);
  const statuses = [...new Set(legs.map((leg) => leg.status))];
  const total = rows.find(
    (leg) => leg.group_total_premium,
  )?.group_total_premium;
  const summary = legs.find((leg) => leg.decision.summary)?.decision.summary;
  const expected = exposure?.expected_count;
  const declined = legs.filter((leg) => leg.status === "declined");
  return (
    <article className="hedge-card playoff-card" data-testid="playoff-card">
      <div className="row">
        <span className="eyebrow">Playoff season protection</span>
        <span className="badges">
          {statuses.map((status) => (
            <span key={status} className={`chip ${status}`}>
              {label(status)}
            </span>
          ))}
        </span>
      </div>
      <h3>If the {team} go out early, these pay you back</h3>
      {exposure && (
        <p className="stake">
          Each extra {team} home playoff game brings about{" "}
          <strong>{fmtUsd(exposure.effect_usd)}</strong>
          {expected !== undefined && expected !== null && (
            <>
              {" "}
              · about <strong>{String(expected)}</strong> home games expected
              this season
            </>
          )}
          {exposure.estimated && (
            <>
              {" "}
              <EstimatedBadge kind="estimated" />
            </>
          )}
        </p>
      )}
      <p>
        If the {team} go out early, these pay you back for the home games you
        didn’t get. If they keep winning, the extra home nights cover the cost.
      </p>
      {summary && <p className="muted">{summary}</p>}
      <table className="legs">
        <caption>
          {legs.length} contract{legs.length === 1 ? "" : "s"}, one per stage of
          the run
        </caption>
        <thead>
          <tr>
            <th scope="col">Pays if</th>
            <th scope="col">Price</th>
            <th scope="col">Contracts</th>
            <th scope="col">Premium</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((leg) => (
            <tr key={leg.id}>
              <th scope="row" className="text-left">
                {leg.leg_label ?? leg.market_title ?? "No matching market"}
                {leg.ticker && (
                  <small>
                    <br />
                    {leg.side.toUpperCase()} · {leg.ticker}
                  </small>
                )}
              </th>
              <td>{leg.avg_price ? fmtCents(leg.avg_price) : "—"}</td>
              <td>
                {leg.n_filled === leg.n_target
                  ? count(leg.n_filled)
                  : `${count(leg.n_filled)} of ${count(leg.n_target)}`}
              </td>
              <td>{leg.premium ? fmtUsd(leg.premium) : "—"}</td>
            </tr>
          ))}
        </tbody>
        {total && (
          <tfoot>
            <tr>
              <th scope="row">Total premium</th>
              <td colSpan={3}>
                <strong>{fmtUsd(total)}</strong>
              </td>
            </tr>
          </tfoot>
        )}
      </table>
      {legs.some((leg) => leg.fee !== null) && (
        <p className="muted">Premiums include Kalshi fees.</p>
      )}
      {declined.length > 0 && (
        <ul className="checks">
          {declined.map((leg) => (
            <li key={leg.id}>
              {(leg as HedgeLeg).leg_label ?? leg.ticker ?? leg.id}:{" "}
              {leg.decision.reasons.map(label).join("; ")}
            </li>
          ))}
        </ul>
      )}
      {exposure?.basis_note && <small>{exposure.basis_note}</small>}
      <GroupApprove legs={legs} onChanged={onChanged} />
    </article>
  );
}
