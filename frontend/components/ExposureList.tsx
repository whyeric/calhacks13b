import type { Exposure, ModelCheckData } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { label } from "@/lib/labels";
import { chartDomain, position } from "@/lib/chartScale";
export function ExposureBar({
  exposure,
  domain,
}: {
  exposure: Exposure;
  domain: [number, number];
}) {
  return (
    <svg
      viewBox="0 0 100 12"
      role="img"
      aria-label={`90% interval ${fmtUsd(exposure.ci90[0])} to ${fmtUsd(exposure.ci90[1])}`}
    >
      <line
        x1={position("0", domain)}
        x2={position("0", domain)}
        y1="0"
        y2="12"
        stroke="#909d96"
      />
      <line
        x1={position(exposure.ci90[0], domain)}
        x2={position(exposure.ci90[1], domain)}
        y1="6"
        y2="6"
        stroke="#247153"
        strokeWidth="2"
      />
      <circle
        cx={position(exposure.effect_usd, domain)}
        cy="6"
        r="2"
        fill="#153f31"
      />
    </svg>
  );
}
export function ExposureList({ exposures }: { exposures: Exposure[] }) {
  const domain = chartDomain(
    exposures.flatMap((row) => [...row.ci90, row.effect_usd]),
  );
  if (!exposures.length) return <p>No measurable exposures yet.</p>;
  return (
    <ul className="exposures">
      {exposures.map((row) => (
        <li key={row.id}>
          <div className="row">
            <strong>{label(row.event)}</strong>
            <span className="value">{fmtUsd(row.effect_usd)}</span>
          </div>
          <p>
            {row.direction === "positive"
              ? "Revenue rises on event days"
              : "Revenue falls on event days"}
          </p>
          <ExposureBar exposure={row} domain={domain} />
          <small>
            90% interval {fmtUsd(row.ci90[0])} to {fmtUsd(row.ci90[1])}
          </small>
        </li>
      ))}
    </ul>
  );
}
export function NotHedgedList({ dropped }: { dropped: Exposure[] }) {
  return (
    <details className="subsection">
      <summary>Measured, not hedged ({dropped.length})</summary>
      {dropped.map((row) => (
        <p key={row.id}>
          <strong>{label(row.event)}</strong> ·{" "}
          {row.reasons.map(label).join("; ")}
        </p>
      ))}
    </details>
  );
}
export function ModelCheck({
  data,
  r2,
}: {
  data: ModelCheckData;
  r2: number | null;
}) {
  return (
    <section className="subsection">
      <h3>Model check</h3>
      <p>We plant a known effect and check what the model recovers.</p>
      <dl className="model-values">
        <div>
          <dt>Planted</dt>
          <dd>{fmtUsd(data.planted_usd)}</dd>
        </div>
        <div>
          <dt>Recovered</dt>
          <dd>{fmtUsd(data.example.recovered)}</dd>
        </div>
      </dl>
      <p>
        90% interval: {fmtUsd(data.example.ci90[0])} to{" "}
        {fmtUsd(data.example.ci90[1])}
      </p>
      <p>
        Coverage {fmtPct(String(data.coverage))} · {data.n_seeds} trials
      </p>
      <p>Holdout R²: {r2 ?? "Not available (no holdout rows)"}</p>
    </section>
  );
}
