import Link from "next/link";
import { BrandMark } from "@/components/BrandMark";
import type { Business } from "@/lib/types";
import { fmtUsd } from "@/lib/format";
export function EstimatedBadge({
  kind,
  note,
}: {
  kind: "real" | "estimated" | "simulated";
  note?: string;
}) {
  return (
    <span className={`badge ${kind}`} title={note}>
      {kind === "real"
        ? "Real"
        : kind === "estimated"
          ? "Estimated"
          : "Simulated"}
      {note && <span> · {note}</span>}
    </span>
  );
}
export function Header({
  businesses,
  selectedId,
  onSelect,
  onRun,
  running,
  onUpload,
}: {
  businesses: Business[];
  selectedId: string;
  onSelect: (id: string) => void;
  onRun: () => void;
  running: boolean;
  onUpload?: () => void;
}) {
  const business = businesses.find((row) => row.id === selectedId);
  return (
    <header>
      <div className="brand">
        <BrandMark />
        <div>
          <h1>Offset</h1>
          <p>Steadier weeks. Your call.</p>
        </div>
      </div>
      <Link href="/research" className="research-link">
        Why this works
      </Link>
      <div className="business-picker">
        <label htmlFor="business">Your business</label>
        <select
          id="business"
          value={selectedId}
          onChange={(e) => onSelect(e.target.value)}
        >
          {businesses.map((row) => (
            <option key={row.id} value={row.id}>
              {row.name}
              {row.uploaded ? " · Uploaded" : ""}
            </option>
          ))}
        </select>
        {business?.uploaded ? (
          <span className="badge uploaded">Uploaded · sample</span>
        ) : (
          business && (
            <EstimatedBadge
              kind={business.estimated ? "estimated" : "real"}
              note={business.estimated ? "visits × average check" : undefined}
            />
          )
        )}
      </div>
      {business && (
        <dl className="budget">
          <div>
            <dt>Weekly budget</dt>
            <dd>{fmtUsd(business.budget.budget)}</dd>
          </div>
          <div>
            <dt>Spent</dt>
            <dd>{fmtUsd(business.budget.spent)}</dd>
          </div>
          <div>
            <dt>Pending</dt>
            <dd>{fmtUsd(business.budget.pending)}</dd>
          </div>
          <div>
            <dt>Remaining</dt>
            <dd>{fmtUsd(business.budget.remaining)}</dd>
          </div>
        </dl>
      )}
      {onUpload && <button onClick={onUpload}>Upload your revenue</button>}
      <button
        className="primary"
        onClick={onRun}
        disabled={running || !business || business.scripted}
      >
        {running ? "Running…" : "Run desk →"}
      </button>
    </header>
  );
}
