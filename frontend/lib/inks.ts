// Blotter inks shared by charts and stamps. Hex values mirror the tokens in
// app/globals.css (--pencil, --ledger), since SVG fills in Recharts take literals.
export const PENCIL = "#a4ada4";
export const LEDGER = "#1f5c45";

export type Ink = "green" | "red" | "amber" | "violet" | "blue" | "pencil";

// Bookkeeping convention: green for the desk's good outcomes, red for declines,
// amber for anything waiting on the owner.
export const STATUS_INK: Record<string, Ink> = {
  proposed: "green",
  approved: "green",
  settled: "green",
  pending_approval: "amber",
  declined: "red",
  rejected: "red",
  expired_unapproved: "red",
};
