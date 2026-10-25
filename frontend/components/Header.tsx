import Link from "next/link";
import { BrandMark } from "@/components/BrandMark";
import type { Business } from "@/lib/types";
import { fmtUsd } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Stamp } from "@/components/ui/stamp";

const INK = { real: "green", estimated: "amber", simulated: "violet" } as const;
// A negative figure is written in red ink. Reads the formatted sign only; no math.
const inkFor = (value: string) =>
  String(value).trim().startsWith("-") ? "negative" : undefined;

export function EstimatedBadge({
  kind,
  note,
}: {
  kind: "real" | "estimated" | "simulated";
  note?: string;
}) {
  return (
    <Stamp ink={INK[kind]} className={`badge ${kind}`} title={note}>
      {kind === "real"
        ? "Real"
        : kind === "estimated"
          ? "Estimated"
          : "Simulated"}
      {note && <span> · {note}</span>}
    </Stamp>
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
          <Stamp ink="blue" className="badge uploaded">
            Uploaded · sample
          </Stamp>
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
            <dd className={inkFor(String(business.budget.budget))}>
              {fmtUsd(business.budget.budget)}
            </dd>
          </div>
          <div>
            <dt>Spent</dt>
            <dd className={inkFor(String(business.budget.spent))}>
              {fmtUsd(business.budget.spent)}
            </dd>
          </div>
          <div>
            <dt>Pending</dt>
            <dd className={inkFor(String(business.budget.pending))}>
              {fmtUsd(business.budget.pending)}
            </dd>
          </div>
          <div>
            <dt>Remaining</dt>
            <dd className={inkFor(String(business.budget.remaining))}>
              {fmtUsd(business.budget.remaining)}
            </dd>
          </div>
        </dl>
      )}
      {onUpload && (
        <Button variant="outline" onClick={onUpload}>
          Upload your revenue
        </Button>
      )}
      <Button
        className="primary"
        onClick={onRun}
        disabled={running || !business || business.scripted}
      >
        {running ? "Running…" : "Run desk →"}
      </Button>
    </header>
  );
}
