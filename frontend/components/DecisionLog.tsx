import type { LogEntry } from "@/lib/types";
import { label } from "@/lib/labels";
import { CheckMetrics } from "./HedgeCard";
export function DecisionRow({ entry }: { entry: LogEntry }) {
  return (
    <details className="decision-row">
      <summary>
        <span className="eyebrow">
          {label(entry.kind)} · {entry.actor}
        </span>
        <time dateTime={entry.created_at}>
          {new Date(entry.created_at).toLocaleTimeString("en-US", {
            hour: "2-digit",
            minute: "2-digit",
            timeZone: "America/New_York",
          })}{" "}
          ET
        </time>
        <span className="log-summary">{entry.summary}</span>
        {entry.agent === "fallback" && (
          <span className="badge">Automatic summary</span>
        )}
      </summary>
      <CheckMetrics checks={entry.checks} />
      {entry.status && <p>{label(entry.status)}</p>}
    </details>
  );
}
export function DecisionLog({ decisions }: { decisions: LogEntry[] }) {
  return (
    <>
      {[...decisions]
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .map((entry) => (
          <DecisionRow key={entry.log_id} entry={entry} />
        ))}
      {!decisions.length && <p>No decisions yet. Run the desk to begin.</p>}
    </>
  );
}
