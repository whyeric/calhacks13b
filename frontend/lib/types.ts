import type { components } from "./schema";
export type Business = components["schemas"]["Business"];
export type Analyze = components["schemas"]["AnalyzeResponse"];
export type Hedge = components["schemas"]["Hedge"];
export type LogEntry = components["schemas"]["LogEntry"];
export type Check = components["schemas"]["Check"];
export type Exposure = components["schemas"]["Exposure"];
export type ModelCheckData = components["schemas"]["ModelCheck"];
export type PayoffRow = components["schemas"]["PayoffRow"];
export type Headline = components["schemas"]["Headline"];
export type Run = components["schemas"]["RunStatus"];
export type Backtest = components["schemas"]["BacktestResult"];
export type Ledger = components["schemas"]["LedgerResponse"];
export type LedgerEntry = components["schemas"]["LedgerEntry"];
export type Reconciliation = components["schemas"]["ReconResult"];
export type ChatReply = components["schemas"]["ChatReply"];
export type ToolCall = components["schemas"]["ToolCall"];
export type Settings = components["schemas"]["Settings"];
export type Thresholds = components["schemas"]["ThresholdSettings"];
// `sample_week` / `sample_businesses` land on /health in PR #60 (and possibly per hedge);
// optional here so the UI works before and after, treating missing as false / [].
export type Health = components["schemas"]["Health"] & {
  sample_week?: boolean;
  sample_businesses?: string[];
};
export type SampleFlag = { sample_week?: boolean };
// Research-driven additions (playoff_home exposure, multi-leg season hedges).
// All optional so the dashboard renders before and after the backend ships them.
export type ExposureExtras = {
  /** Expected number of occurrences (e.g. playoff home games); API string, shown verbatim. */
  expected_count?: string | number | null;
  /** True when the dollars rest on assumptions (visits × average check). */
  estimated?: boolean;
  /** Plain-language note on what the dollars are based on. */
  basis_note?: string | null;
};
export type ExposureRow = Exposure & ExposureExtras;
// One leg of a multi-contract hedge; legs of one set share an exposure_id.
export type HedgeLeg = Hedge & {
  /** Plain-language name of this leg, e.g. "Knicks miss the playoffs". */
  leg_label?: string | null;
  /** Total premium across every leg of the set, computed by the API. */
  group_total_premium?: string | null;
};
