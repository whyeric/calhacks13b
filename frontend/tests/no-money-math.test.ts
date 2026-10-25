import { ESLint, Linter } from "eslint";
import { expect, it } from "vitest";
import rule from "../eslint-rules/no-money-math.mjs";
it("C7-A1 checks all application code with the enforced lint rule", async () => {
  const lint = new ESLint();
  const results = await lint.lintFiles(["app", "components", "lib"]);
  expect(
    results.flatMap((row) =>
      row.messages.filter(
        (message) => message.ruleId === "hedge/no-money-math",
      ),
    ),
  ).toEqual([]);
}, 20000);
it("C7-A1 rejects arithmetic, coercion and financial libraries", () => {
  const lint = new Linter();
  for (const code of [
    "premium - fee",
    "row.cost + 1",
    "+budget",
    "Number(value)",
    "parseFloat(value)",
    "Math.round(value)",
    "import Decimal from 'decimal.js'",
  ]) {
    expect(
      lint.verify(code, [
        {
          plugins: { hedge: { rules: { math: rule } } },
          rules: { "hedge/math": "error" },
        },
      ]).length,
    ).toBeGreaterThan(0);
  }
});
