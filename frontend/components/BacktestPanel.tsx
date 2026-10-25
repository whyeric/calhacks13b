"use client";
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer } from "recharts";
import type { Backtest } from "@/lib/types";
import { fmtUsd } from "@/lib/format";
import { label } from "@/lib/labels";
import { chartSeries } from "@/lib/chartScale";
import { EstimatedBadge } from "./Header";

// Stats such as reduction_pct are plain numbers from the API; shown verbatim.
const pct = (value: number) => `${value}%`;
export function weekLabel(date: string) {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}
export function BacktestHeadline({ data }: { data: Backtest }) {
  return (
    <p className="backtest-headline">
      Weekly income swings {data.reduction_pct >= 0 ? "fell" : "changed by"}{" "}
      <strong>{pct(data.reduction_pct)}</strong> for{" "}
      <strong>{fmtUsd(data.total_premium)}</strong> in premiums
    </p>
  );
}
export function PricingLabel({ data }: { data: Backtest }) {
  if (data.priced_real_pct >= 100)
    return <span className="badge real">Priced from real Kalshi prices</span>;
  return (
    <span className="badge estimated">
      {pct(data.priced_real_pct)} priced from real Kalshi prices · the rest
      frequency-priced
    </span>
  );
}
export function MetricsStrip({ data }: { data: Backtest }) {
  return (
    <dl className="metrics-strip">
      <div>
        <dt>Worst week · {weekLabel(data.worst_week_unhedged.week_start)}</dt>
        <dd>
          {fmtUsd(data.worst_week_unhedged.income)} unhedged →{" "}
          {fmtUsd(data.worst_week_hedged.income)} hedged
        </dd>
      </div>
      <div>
        <dt>Typical weekly swing</dt>
        <dd>
          {fmtUsd(data.std_unhedged)} → {fmtUsd(data.std_hedged)}
        </dd>
      </div>
      <div>
        <dt>Total premiums</dt>
        <dd>{fmtUsd(data.total_premium)}</dd>
      </div>
      <div>
        <dt>Hedges bought · declined</dt>
        <dd>
          {data.n_hedges} · {data.n_declined}
        </dd>
      </div>
    </dl>
  );
}
export function BacktestPanel({ data }: { data: Backtest }) {
  const series = chartSeries(
    data.weekly.map((row) => ({
      label: weekLabel(row.week_start),
      unhedged: row.unhedged,
      hedged: row.hedged,
    })),
    ["unhedged", "hedged"],
  );
  const exposures = Object.entries(data.per_exposure);
  return (
    <div className="backtest" data-testid="backtest-panel">
      <div className="row">
        <BacktestHeadline data={data} />
        <div className="badges">
          <PricingLabel data={data} />
          {data.estimated && (
            <EstimatedBadge kind="estimated" note="visits × average check" />
          )}
        </div>
      </div>
      <MetricsStrip data={data} />
      <div className="backtest-body">
        <div className="backtest-chart" aria-hidden="true">
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={series} accessibilityLayer={false}>
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis hide domain={["auto", "auto"]} />
              <Line
                dataKey="unhedged"
                name="Unhedged"
                stroke="#9aa99e"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                dataKey="hedged"
                name="Hedged"
                stroke="#247153"
                strokeWidth={3}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
          <p className="legend">Grey: unhedged income · Green: hedged income</p>
        </div>
        <ul className="per-exposure">
          {exposures.map(([key, row]) => (
            <li key={key} className={row.ineffective ? "ineffective" : ""}>
              <strong>{label(key.replace(/^exp_/, ""))}</strong>
              <span>
                Swings {pct(row.reduction_pct)} smaller ·{" "}
                {fmtUsd(row.total_premium)} premiums
              </span>
              {row.ineffective && (
                <span className="badge declined">
                  Ineffective · under 10% reduction
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
      <details className="weekly-table">
        <summary>Week-by-week numbers</summary>
        <table>
          <caption>Weekly income, unhedged vs. hedged</caption>
          <thead>
            <tr>
              <th scope="col">Week of</th>
              <th scope="col">Unhedged</th>
              <th scope="col">Hedged</th>
              <th scope="col">Premium</th>
            </tr>
          </thead>
          <tbody>
            {data.weekly.map((row) => (
              <tr key={row.week_start}>
                <th scope="row">{weekLabel(row.week_start)}</th>
                <td>{fmtUsd(row.unhedged)}</td>
                <td>{fmtUsd(row.hedged)}</td>
                <td>{fmtUsd(row.premium)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
export function BacktestNotReady({ retry }: { retry: () => void }) {
  return (
    <div className="state" role="status">
      <p>
        <strong>No backtest yet.</strong> The desk has not replayed last season
        for this business, so there are no before-and-after numbers to show.
      </p>
      <button onClick={retry}>Check again</button>
    </div>
  );
}
