// The only numeric coercion of financial strings; used solely for chart geometry.
export function chartDomain(values: string[]): [number, number] {
  const points = values.map(Number);
  return [Math.min(0, ...points), Math.max(1, ...points)];
}
// Numeric copies of API strings for chart geometry only; labels and tables use the strings.
export function chartSeries<K extends string>(
  rows: Record<K | "label", string>[],
  keys: K[],
): Record<string, string | number>[] {
  return rows.map((row) => ({
    label: row.label,
    ...Object.fromEntries(keys.map((key) => [key, Number(row[key])])),
  }));
}
// Horizontal bar from zero to `value`, in percent of the plot width (research page).
export function barSpan(
  value: number,
  domain: [number, number],
): { x: number; width: number } {
  const zero = position("0", domain);
  const end = position(String(value), domain);
  return { x: Math.min(zero, end), width: Math.abs(end - zero) };
}
export function position(value: string, domain: [number, number]): number {
  return ((Number(value) - domain[0]) / (domain[1] - domain[0])) * 100;
}
// Span between two decimal strings (a confidence interval), in percent of the
// plot width (scripted upload demo's forest plot).
export function intervalSpan(
  low: string,
  high: string,
  domain: [number, number],
): { x: number; width: number } {
  const a = position(low, domain);
  const b = position(high, domain);
  return { x: Math.min(a, b), width: Math.abs(b - a) };
}
// Vertical bar from zero to `value` (both in `domain`), in SVG units, plus a label baseline.
export function columnSpan(
  value: string,
  domain: [number, number],
  top: number,
  height: number,
): { y: number; height: number; labelY: number } {
  const at = (v: string) => top + (1 - position(v, domain) / 100) * height;
  const y0 = at("0");
  const y1 = at(value);
  return { y: Math.min(y0, y1), height: Math.max(Math.abs(y1 - y0), 1.5), labelY: Math.max(y0, y1) + 14 };
}
// Symmetric $/day axis for the live research forest plot, from the API's largest |CI end|,
// with ticks at a round step ("-3000", "-1500", "0", …) and short labels ("−$3k").
export function forestAxis(maxAbs: string): {
  domain: [number, number];
  ticks: string[];
} {
  const max = Math.max(Number(maxAbs), 1);
  const raw = max / 2;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 1.5, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ??
    10 * mag;
  const edge = Math.max(max * 1.04, 2 * step * 1.04);
  const ticks = [-2, -1, 0, 1, 2]
    .map((k) => k * step)
    .filter((v) => Math.abs(v) <= edge)
    .map((v) => String(v));
  return { domain: [-edge, edge], ticks };
}
export function tickLabel(value: string): string {
  const v = Number(value);
  if (v === 0) return "$0";
  const sign = v < 0 ? "−" : "";
  const a = Math.abs(v);
  return a >= 1000 ? `${sign}$${a / 1000}k` : `${sign}$${a}`;
}
// Whole-number percent for a progress bar driven by an easing function.
export function progressPercent(fraction: number): number {
  return Math.round(Math.min(Math.max(fraction, 0), 1) * 100);
}
