"use client";
import { useState } from "react";
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer } from "recharts";
import type {
  Check,
  ExposureRow,
  Hedge,
  Headline,
  PayoffRow,
} from "@/lib/types";
import { PlayoffCard, groupHedges } from "./PlayoffCard";
import { fmtUsd, fmtPct, fmtCents } from "@/lib/format";
import { label } from "@/lib/labels";
import { apiPost } from "@/lib/api";

export function DecisionChip({ status }: { status: Hedge["status"] }) {
  return <span className={`chip ${status}`}>{label(status)}</span>;
}
export function HeadlineStrip({ headline }: { headline: Headline }) {
  return (
    <p className="headline">
      Unhedged swing {fmtUsd(headline.unhedged_swing)} · hedged swing{" "}
      {fmtUsd(headline.hedged_swing)} · cost {fmtUsd(headline.cost)}
    </p>
  );
}
function metric(key: string, value: string | number | boolean | null) {
  if (value === null) return "Not available";
  if (typeof value !== "string" || !/^-?\d+(\.\d+)?$/.test(value))
    return String(value);
  if (["avg_price", "price"].includes(key)) return fmtCents(value);
  if (["fair", "overpay", "ratio", "fill_ratio"].includes(key))
    return fmtPct(value);
  if (
    /usd|premium|cost|swing|payout|effect|revenue|budget|remaining|beta/.test(
      key,
    )
  )
    return fmtUsd(value);
  return value;
}
export function CheckMetrics({ checks }: { checks: Check[] }) {
  return (
    <ul className="checks">
      {checks.map((check) => (
        <li key={check.code}>
          <strong>{label(check.code)}</strong> ·{" "}
          {check.passed === null ? "Skipped" : check.passed ? "Pass" : "Fail"}
          <dl>
            {Object.entries(check.metric).map(([key, value]) => (
              <div key={key}>
                <dt>{label(key)}</dt>
                <dd>{metric(key, value)}</dd>
              </div>
            ))}
          </dl>
        </li>
      ))}
    </ul>
  );
}
const LAST_YEAR = ["effect_last_year_usd", "effect_train_usd"];
const RECENT = ["effect_recent_usd", "effect_holdout_usd"];
const pick = (metric: Check["metric"], keys: string[]) => {
  const value = keys.map((key) => metric[key]).find((v) => v !== undefined);
  return typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value)
    ? value
    : null;
};
// "unstable": the effect was refit on recent months and didn't hold up.
export function UnstableNote({ checks }: { checks: Check[] }) {
  // "unstable" is newer than the generated schema enum.
  const check = checks.find((row) => (row.code as string) === "unstable");
  if (!check) return null;
  const lastYear = pick(check.metric, LAST_YEAR);
  const recent = pick(check.metric, RECENT);
  if (!lastYear && !recent) return null;
  return (
    <dl className="unstable-compare" aria-label="Effect last year vs recent">
      <div>
        <dt>Last year</dt>
        <dd>{lastYear ? fmtUsd(lastYear) : "Not available"}</dd>
      </div>
      <div>
        <dt>Recent months</dt>
        <dd>{recent ? fmtUsd(recent) : "Not available"}</dd>
      </div>
    </dl>
  );
}
export function DeclineReasons({ hedge }: { hedge: Hedge }) {
  return (
    <div className="decline-reasons">
      <ul>
        {hedge.decision.reasons.map((reason) => (
          <li key={reason}>{label(reason)}</li>
        ))}
      </ul>
      <UnstableNote checks={hedge.decision.checks} />
      <CheckMetrics
        checks={hedge.decision.checks.filter((check) => check.passed === false)}
      />
    </div>
  );
}
const outcomes: Record<string, [string, string]> = {
  rain: ["It rains", "It stays dry"],
  hot: ["Hot day", "Cooler day"],
  home_win: ["Home team wins", "Home team loses"],
};
export function PayoffChart({
  rows,
  event = "rain",
}: {
  rows: PayoffRow[];
  event?: string;
}) {
  const names = outcomes[event] ?? ["Event", "No event"];
  return (
    <div className="payoff">
      <div className="chart" aria-hidden="true">
        <ResponsiveContainer width="100%" height={130}>
          <BarChart data={rows} accessibilityLayer={false}>
            <XAxis
              dataKey="outcome"
              tickFormatter={(v) => (v === "event" ? names[0] : names[1])}
            />
            <YAxis hide />
            <Bar
              dataKey="revenue_vs_base"
              name="Unhedged"
              fill="#9aa99e"
              isAnimationActive={false}
            />
            <Bar
              dataKey="net_vs_base"
              name="Hedged"
              fill="#247153"
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="legend">Unhedged revenue / Hedged net, including cost</p>
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
          {rows.map((row) => (
            <tr key={row.outcome}>
              <th scope="row">
                {row.outcome === "event" ? names[0] : names[1]}
              </th>
              <td>{fmtUsd(row.revenue_vs_base)}</td>
              <td>{fmtUsd(row.contract_payout)}</td>
              <td>{fmtUsd(row.premium)}</td>
              <td>{fmtUsd(row.net_vs_base)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function ApproveBar({
  hedge,
  onChanged,
}: {
  hedge: Hedge;
  onChanged: () => Promise<unknown>;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  if (!["proposed", "pending_approval"].includes(hedge.status)) return null;
  async function decide(action: string) {
    setPending(true);
    setError("");
    try {
      await apiPost(`/hedges/${encodeURIComponent(hedge.id)}/${action}`, {
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
      {hedge.alternative && (
        <aside className="alternative">
          <strong>Within-budget alternative</strong>
          <p>
            {hedge.alternative.n_filled} contracts ·{" "}
            {fmtUsd(hedge.alternative.premium)} premium
          </p>
          <HeadlineStrip headline={hedge.alternative.headline} />
        </aside>
      )}
      <div className="row">
        <p>Only you can approve protection.</p>
        <div className="actions">
          <button disabled={pending} onClick={() => decide("reject")}>
            Reject
          </button>
          <button
            className="primary"
            disabled={pending}
            onClick={() => decide("approve")}
          >
            {pending ? "Saving…" : "Approve"}
          </button>
        </div>
      </div>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
// The order the owner's approval placed on Kalshi's demo exchange (markets/trading.py).
// Fake money, so it is always labeled; the ledger keeps the approved figures, and a fill
// that differs is left for reconciliation to flag.
export function VenueOrderLine({
  order,
}: {
  order: NonNullable<Hedge["venue_order"]>;
}) {
  const filled =
    order.status === "filled" || order.status === "partial"
      ? `${order.status === "filled" ? "Filled" : "Partly filled"} ${order.filled} of ${order.requested}${order.avg_price ? ` at ${fmtCents(order.avg_price)}` : ""}`
      : order.status === "failed"
        ? "Order failed"
        : "Not placed";
  return (
    <p className="venue-order" data-testid="venue-order">
      <span className="badge simulated">Kalshi demo · fake money</span> {filled}
      {order.stand_in && order.ticker && (
        <> · demo stand-in {order.ticker}, not the production contract</>
      )}
      {order.reason && <> · {order.reason}</>}
      {order.differs_from_booked && (
        <> · differs from what was booked; reconciliation will flag it</>
      )}
    </p>
  );
}
export function HedgeCard({
  hedge,
  onChanged,
}: {
  hedge: Hedge;
  onChanged: () => Promise<unknown>;
}) {
  const event = hedge.exposure_id.replace(/^exp_/, "");
  return (
    <article className="hedge-card" data-testid="hedge-card">
      <div className="row">
        <span className="eyebrow">{label(event)} protection</span>
        <DecisionChip status={hedge.status} />
      </div>
      <h3>{hedge.market_title ?? "No matching market"}</h3>
      {hedge.ticker && (
        <p className="muted">
          Buy {hedge.side.toUpperCase()} · {hedge.n_filled} of {hedge.n_target}{" "}
          contracts{hedge.partial ? " · Partial fill" : ""}
          {hedge.resized ? " · Resized to match exposure" : ""}
        </p>
      )}
      {hedge.decision.summary && <p>{hedge.decision.summary}</p>}
      {hedge.status === "declined" && <DeclineReasons hedge={hedge} />}
      {hedge.headline && hedge.status !== "declined" && (
        <HeadlineStrip headline={hedge.headline} />
      )}
      {hedge.payoff && <PayoffChart rows={hedge.payoff} event={event} />}
      {hedge.premium !== null && (
        <p>
          Premium {fmtUsd(hedge.premium)}
          {hedge.fee !== null && <> · includes {fmtUsd(hedge.fee)} in fees</>}
        </p>
      )}
      {hedge.venue_order && <VenueOrderLine order={hedge.venue_order} />}
      {hedge.market_url && (
        <a href={hedge.market_url} target="_blank" rel="noopener noreferrer">
          Open on Kalshi ↗
        </a>
      )}
      <ApproveBar hedge={hedge} onChanged={onChanged} />
    </article>
  );
}
export function HedgeList({
  hedges,
  onChanged,
  exposures = [],
}: {
  hedges: Hedge[];
  onChanged: () => Promise<unknown>;
  exposures?: ExposureRow[];
}) {
  const items = groupHedges(hedges);
  return (
    <>
      <div className="section-heading">
        <h2>This week’s protection</h2>
        <span className="badge">{items.length} decisions</span>
      </div>
      {items.length ? (
        items.map((item) =>
          Array.isArray(item) ? (
            <PlayoffCard
              key={item[0].id}
              legs={item}
              exposure={exposures.find((row) => row.id === item[0].exposure_id)}
              onChanged={onChanged}
            />
          ) : (
            <HedgeCard key={item.id} hedge={item} onChanged={onChanged} />
          ),
        )
      ) : (
        <p className="state">No hedges this week. Run the desk.</p>
      )}
    </>
  );
}
