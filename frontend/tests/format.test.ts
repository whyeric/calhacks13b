import { describe, expect, it } from "vitest";
import { fmtUsd, fmtPct, fmtCents } from "@/lib/format";
describe("C7-A3 exact decimal-string formatting", () => {
  it.each([
    ["1240.0", "$1,240"],
    ["0.5", "$0.50"],
    ["1234.50", "$1,234.50"],
    ["-10000.01", "−$10,000.01"],
    ["9007199254740993.29", "$9,007,199,254,740,993.29"],
    ["0.00", "$0"],
  ])("formats %s", (input, expected) => expect(fmtUsd(input)).toBe(expected));
  it("moves decimal points without rounding", () => {
    expect(fmtPct("0.27")).toBe("27%");
    expect(fmtCents("0.62")).toBe("62¢");
    expect(fmtPct("0.3665")).toBe("36.65%");
    expect(fmtCents("-0.0001")).toBe("−0.01¢");
  });
});
