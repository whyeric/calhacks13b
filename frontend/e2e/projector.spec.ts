import { expect, test } from "@playwright/test";
// These specs cover the dashboard: start past the first-run setup wizard.
test.beforeEach(({ page }) =>
  page.addInitScript(() =>
    window.localStorage.setItem("hedge-desk:setup-done", "1"),
  ),
);
test("C7-A31 projector dashboard fits and shows all regions above fold", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await page.goto("/");
  await expect(page.getByTestId("hedge-card")).toHaveCount(3);
  for (const name of ["Revenue exposures", "Hedge decisions", "Decision log"]) {
    const box = await page
      .getByRole("region", { name, exact: true })
      .boundingBox();
    expect(box!.y).toBeLessThan(720);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  for (const el of await page.locator(".hedge-card,.log-panel").all())
    expect(
      await el.evaluate((node) => node.scrollWidth <= node.clientWidth),
    ).toBe(true);
  // The freshness line shows the clock time, so it is masked.
  await expect(page).toHaveScreenshot("dashboard-1280.png", {
    fullPage: true,
    mask: [page.getByTestId("freshness")],
  });
  expect(errors).toEqual([]);
});
test("C7-A32 1024px stacks without horizontal scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/");
  await expect(page.getByTestId("hedge-card")).toHaveCount(3);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const left = await page.locator(".exposure-panel").boundingBox();
  const middle = await page.locator(".hedges-panel").boundingBox();
  expect(middle!.y).toBeGreaterThan(left!.y);
});
test("mock actions, business switch and run polling", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("hedge-card")).toHaveCount(3);
  await page
    .getByRole("button", { name: "Approve", exact: true })
    .first()
    .click();
  await expect(
    page.getByText("Approved", { exact: true }).first(),
  ).toBeVisible();
  await page.getByLabel("Your business").selectOption("restaurant");
  await expect(page.getByText(/visits × average check/)).toBeVisible();
  await expect(
    page.getByText("Revenue falls on event days").first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Run desk" }).click();
  await expect(page.getByRole("button", { name: "Running…" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Run desk" })).toBeEnabled();
});
for (const scenario of ["empty", "error", "slow", "longtext", "negative"])
  test(`scenario ${scenario}`, async ({ page }) => {
    await page.goto(`/?scenario=${scenario}`);
    await expect(page.getByText(/MOCK DATA/)).toBeVisible();
    if (scenario === "empty")
      await expect(
        page.getByText("No hedges this week. Run the desk."),
      ).toBeVisible();
    else if (scenario === "error") {
      await expect(
        page.getByRole("button", { name: "Retry", exact: true }),
      ).toHaveCount(4); // exposures, hedges, decision log, backtest (#28)
    } else {
      await expect(page.getByTestId("hedge-card")).toHaveCount(3);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
    await expect(page.locator("body")).not.toContainText(
      /undefined|NaN|\$null/,
    );
  });
