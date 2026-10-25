import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LedgerTab, ReconcilePanel } from "@/components/LedgerTab";
import type { Ledger } from "@/lib/types";
import ledgerJson from "@/fixtures/ledger_with_mismatch.json";
const ledger = structuredClone(ledgerJson) as Ledger;
const noop = async () => {};

describe("C7-A8 simulated labels (I6)", () => {
  it("ledger tab shows a visible, non-dismissible Simulated badge", () => {
    render(<LedgerTab ledger={ledger} businessId="taxi" onReconciled={noop} />);
    const tab = screen.getByTestId("ledger-tab");
    const badges = within(tab).getAllByText("Simulated", { exact: true });
    expect(badges.length).toBeGreaterThan(0);
    badges.forEach((badge) => expect(badge).toBeVisible());
    // Visible text, not a hover-only tooltip, and nothing to close it with.
    expect(
      within(tab).getByText(/settlements and the bank statement are simulated/),
    ).toBeVisible();
    expect(
      within(tab).queryByRole("button", { name: /dismiss|close|hide/i }),
    ).not.toBeInTheDocument();
  });
  it("labels every simulated entry row in text", () => {
    render(<LedgerTab ledger={ledger} businessId="taxi" onReconciled={noop} />);
    const entries = screen.getByRole("region", { name: "Ledger entries" });
    const rows = within(entries).getAllByRole("row").slice(1);
    ledger.entries.forEach((entry, i) => {
      if (entry.simulated)
        expect(within(rows[i]).getByText("Simulated")).toBeVisible();
      else
        expect(
          within(rows[i]).queryByText("Simulated"),
        ).not.toBeInTheDocument();
    });
  });
  it("ReconcilePanel labels the bank statement as simulated", () => {
    render(
      <ReconcilePanel
        reconciliation={ledger.reconciliation}
        businessId="taxi"
        onReconciled={noop}
      />,
    );
    const panel = screen.getByRole("region", { name: "Reconciliation" });
    expect(within(panel).getByText("Simulated")).toBeVisible();
    expect(within(panel).getByText("Bank (simulated)")).toBeVisible();
  });
});
