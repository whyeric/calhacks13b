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
