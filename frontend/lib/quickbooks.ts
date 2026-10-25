// Display helpers for the QuickBooks Online integration. Formatting only: every figure and
// total is an API string shown as is (I2; the no-money-math lint rule applies).
import { ApiError, errorCode } from "./api";
import type { CommitmentLine, QuickBooksResearch } from "./types";

export const QBO_NAME = "QuickBooks Online";

// "QuickBooks Online · 1,004 days · 2024-01-01 to 2026-09-30"
export const quickBooksSummary = (r: QuickBooksResearch) =>
  `${QBO_NAME} · ${r.days.toLocaleString("en-US")} ${r.days === 1 ? "day" : "days"} · ${r.first_day} to ${r.last_day}`;

// Earliest due date first; lines with no due date go last. String order on YYYY-MM-DD.
export const byDueDate = (rows: CommitmentLine[]) =>
  [...rows].sort((a, b) =>
    a.due_date === b.due_date
      ? 0
      : a.due_date === null
        ? 1
        : b.due_date === null
          ? -1
          : a.due_date.localeCompare(b.due_date),
  );

// Quantities are Decimal strings; drop an all-zero fraction ("38.00" → "38").
export const fmtQty = (value: string) => value.replace(/\.0+$/, "");

const MESSAGES: Record<string, string> = {
  not_connected: "QuickBooks isn’t connected. Connect it, then try again.",
  quickbooks_unavailable:
    "QuickBooks didn’t answer just now. Please try again in a minute.",
};
export function quickBooksErrorText(err: unknown, fallback: string): string {
  const code = errorCode(err);
  if (code && MESSAGES[code]) return MESSAGES[code];
  if (err instanceof ApiError) return err.message;
  if (err instanceof TypeError)
    return "We couldn’t reach your desk server. Please retry.";
  return err instanceof Error && err.message ? err.message : fallback;
}

export const QBO_RETURN_ERROR =
  "QuickBooks didn’t finish connecting. Please try again.";
