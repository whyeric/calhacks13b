import { expect, test, type Page } from "@playwright/test";
// Upload drawer → POST /research (served by the mock: the backend's example
// research_response.json) → the report. Starts past the setup wizard.
test.beforeEach(({ page }) =>
  page.addInitScript(() =>
    window.localStorage.setItem("hedge-desk:setup-done", "1"),
  ),
);
async function uploadSample(page: Page, query = "") {
  await page.goto(`/${query}`);
  await page.getByRole("button", { name: "Upload your revenue" }).click();
  const drawer = page.getByRole("dialog", { name: "Upload your revenue" });
  await drawer.getByRole("button", { name: "Use the sample file" }).click();
  await expect(drawer.getByRole("status")).toContainText("1,004 days");
  await drawer.getByRole("button", { name: "Upload and research" }).click();
  return drawer;
}

test("upload → live research report, send only the sendable row", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await uploadSample(page);
  const report = page.getByTestId("demo-research");
  await expect(report.getByTestId("research-row-rain")).toContainText(
    "−18.4% · −$1,955.68/day",
  );
  await expect(report).toContainText(
    "Hudson Bike Co. · 1,004 days · 2024-01-01 → 2026-09-30",
  );
  await expect(page.getByText("Running analysis…")).toHaveCount(0);
  await expect(page.getByText("Precomputed on the sample file")).toHaveCount(0);
  await expect(
    report.getByRole("button", { name: /Send to the desk/ }),
  ).toHaveCount(1);
  await report.getByRole("button", { name: /Send to the desk/ }).click();
  await expect(page.getByTestId("demo-hedge-card")).toContainText(
    "Proposed · only you can approve",
  );
  expect(errors).toEqual([]);
});

test("a rejected file shows the 422 message in the drawer", async ({
  page,
}) => {
  const drawer = await uploadSample(page, "?scenario=bad_csv");
  await expect(drawer.getByRole("alert")).toHaveText(
    "We need at least 540 days with revenue to research your risks; this file has 120.",
  );
  await expect(page.getByTestId("demo-research")).toHaveCount(0);
});

test("API failure falls back to the labeled precomputed report", async ({
  page,
}) => {
  await uploadSample(page, "?scenario=error");
  await expect(page.getByText("Precomputed on the sample file")).toBeVisible();
  await expect(page.getByTestId("research-row-rain")).toBeVisible();
});
