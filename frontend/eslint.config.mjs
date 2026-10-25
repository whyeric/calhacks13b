import { FlatCompat } from "@eslint/eslintrc";
import { fileURLToPath } from "node:url";
import noMoneyMath from "./eslint-rules/no-money-math.mjs";
const compat = new FlatCompat({
  baseDirectory: fileURLToPath(new URL(".", import.meta.url)),
});
export default [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      ".python-tools/**",
      "lib/schema.ts",
      "test-results/**",
      "playwright-report/**",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    files: [
      "app/**/*.{ts,tsx}",
      "components/**/*.{ts,tsx}",
      "lib/**/*.{ts,tsx}",
    ],
    plugins: { hedge: { rules: { "no-money-math": noMoneyMath } } },
    rules: { "hedge/no-money-math": "error" },
  },
];
