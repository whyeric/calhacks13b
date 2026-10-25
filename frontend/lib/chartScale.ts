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
export function position(value: string, domain: [number, number]): number {
  return ((Number(value) - domain[0]) / (domain[1] - domain[0])) * 100;
}
