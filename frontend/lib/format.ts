// Decimal strings stay strings: grouping and decimal-point movement only.
function parts(value: string) {
  if (!/^-?\d+(\.\d+)?$/.test(value)) throw new Error("Invalid decimal string");
  const [whole, fraction = ""] = value.replace(/^-/, "").split(".");
  return { sign: value.startsWith("-") ? "−" : "", whole, fraction };
}
export function fmtUsd(value: string): string {
  const { sign, whole, fraction } = parts(value);
  const digits = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}$${digits}${/[1-9]/.test(fraction) ? `.${fraction.padEnd(2, "0")}` : ""}`;
}
function shift(value: string): string {
  const { sign, whole, fraction } = parts(value);
  const digits = `${whole}${fraction.padEnd(2, "0").slice(0, 2)}`.replace(
    /^0+(?=\d)/,
    "",
  );
  const tail = fraction.slice(2).replace(/0+$/, "");
  return `${sign}${digits}${tail ? `.${tail}` : ""}`;
}
export const fmtPct = (value: string): string => `${shift(value)}%`;
export const fmtCents = (value: string): string => `${shift(value)}¢`;
