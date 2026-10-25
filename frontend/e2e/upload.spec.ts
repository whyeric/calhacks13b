import { expect, test, type Page } from "@playwright/test";
// Upload drawer → POST /research (served by the mock: fixtures/research_report.json, a real
// backend run) → the report, with a spinner and no staged delay. Starts past the setup wizard.
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
}

test("upload → live report → card sized from the report", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await uploadSample(page);
  const report = page.getByTestId("demo-research");
  await expect(report.getByTestId("research-row-rain")).toContainText(
    "−18.2% · −$1,923.43/day",
  );
  await expect(page.getByText("Running analysis…")).toHaveCount(0);
  await expect(page.getByTestId("research-precomputed")).toHaveCount(0);
  await expect(
    report.getByRole("button", { name: /Send to the desk/ }),
  ).toHaveCount(1);
  await report.getByRole("button", { name: /Send to the desk/ }).click();
  const card = page.getByTestId("demo-hedge-card");
  await expect(card).toContainText("Proposed · only you can approve");
  await expect(card).toContainText(
    "1,923 contracts @ 33¢ · premium $664.36 (includes $29.77 fee)",
  );
  expect(errors).toEqual([]);
});

test("a rejected file shows the 422 message", async ({ page }) => {
  await uploadSample(page, "?scenario=bad_csv");
  await expect(page.getByTestId("demo-research").getByRole("alert")).toHaveText(
    "Need at least 540 open days inside the weather record; found 120.",
  );
  await expect(page.getByTestId("research-row-rain")).toHaveCount(0);
});

test("API failure falls back to the labeled precomputed report", async ({
  page,
}) => {
  await uploadSample(page, "?scenario=error");
  await expect(page.getByTestId("research-precomputed")).toContainText(
    "Precomputed on the sample file",
  );
  await expect(page.getByTestId("research-row-rain")).toContainText(
    "−18.4% · −$1,955.68/day",
  );
});
