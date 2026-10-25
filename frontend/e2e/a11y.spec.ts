import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
// These specs cover the dashboard: start past the first-run setup wizard.
test.beforeEach(({ page }) =>
  page.addInitScript(() =>
    window.localStorage.setItem("hedge-desk:setup-done", "1"),
  ),
);
test("C7-A33 no serious or critical accessibility violations", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByTestId("hedge-card")).toHaveCount(3);
  const result = await new AxeBuilder({ page }).analyze();
  expect(
    result.violations.filter((row) =>
      ["serious", "critical"].includes(row.impact ?? ""),
    ),
  ).toEqual([]);
});
