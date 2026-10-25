// The only numeric coercion of financial strings; used solely for chart geometry.
export function chartDomain(values: string[]): [number, number] {
  const points = values.map(Number);
  return [Math.min(0, ...points), Math.max(1, ...points)];
}
export function position(value: string, domain: [number, number]): number {
  return ((Number(value) - domain[0]) / (domain[1] - domain[0])) * 100;
}
