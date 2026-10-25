import { expect, test } from "@playwright/test";
test("first run: setup wizard with the MSG demo bar, then the dashboard", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await page.goto("/");
  await expect(page.getByText(/Step 1 of 5/)).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Connect Square / QuickBooks (coming soon)",
    }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Use demo: bar near MSG" }).click();
  const next = page.getByRole("button", { name: "Next →" });
  await next.click();
  await expect(page.getByText(/Step 2 of 5/)).toBeVisible();
  await expect(page.getByText("Declined, and why")).toBeVisible();
  await next.click();
  await expect(page.getByLabel("Weekly budget ($)")).toBeVisible();
  await next.click();
  await expect(
    page.getByText(/Nothing is approved automatically/),
  ).toBeVisible();
  await expect(page.getByTestId("hedge-card").first()).toBeVisible();
  await expect(page.getByText("Approved", { exact: true })).toHaveCount(0);
  await next.click();
  await expect(page.getByText(/Step 5 of 5/)).toBeVisible();
  await page.getByRole("button", { name: "Open my dashboard →" }).click();
  await expect(page.getByLabel("Your business")).toHaveValue("restaurant");
  await expect(page.getByTestId("freshness")).toContainText(
    /Last updated .* · Kalshi prices as of/,
  );

  // Setup is done: a reload opens straight to the dashboard.
  await page.reload();
  await expect(page.getByTestId("hedge-card").first()).toBeVisible();
  await expect(page.getByText(/Step 1 of 5/)).toHaveCount(0);
  await page.getByRole("button", { name: "Re-run setup" }).click();
  await expect(page.getByText(/Step 1 of 5/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("first run with an upload: /research report in step 2", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Upload your revenue" }).click();
  const drawer = page.getByRole("dialog", { name: "Upload your revenue" });
  await drawer.getByRole("button", { name: "Use the sample file" }).click();
  await drawer.getByRole("button", { name: "Upload and research" }).click();
  await expect(page.locator(".wizard-picked")).toContainText(
    "Hudson Bike Co. · 1,004 days · 2024-01-01 → 2026-09-30",
  );
  await page.getByRole("button", { name: "Next →" }).click();
  await expect(page.getByTestId("research-row-rain")).toBeVisible();
  await expect(page.getByText("Declined, and why")).toBeVisible();
  await expect(page.getByText("Precomputed on the sample file")).toHaveCount(0);
});
