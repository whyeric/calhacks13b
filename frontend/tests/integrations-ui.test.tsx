import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReconcilePanel } from "@/components/LedgerTab";
import { VenueOrderLine } from "@/components/HedgeCard";
import type { Hedge, Reconciliation } from "@/lib/types";

// The backend's hand-maintained contract examples, so the UI is tested on the real shapes.
const example = <T,>(name: string): T =>
  JSON.parse(
    readFileSync(
      resolve(process.cwd(), "../backend/fixtures/examples", name),
      "utf-8",
    ),
  ) as T;
const noop = async () => {};

describe("three-way reconciliation", () => {
  const recon = example<Reconciliation>("reconciliation.json");
  it("labels each leg by where it came from", () => {
    render(
      <ReconcilePanel
        reconciliation={recon}
        businessId="taxi"
        onReconciled={noop}
      />,
    );
    const headers = within(screen.getByRole("table"))
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toContain("Venue (simulated)");
    expect(headers).toContain("Bank (simulated)");
    expect(
      screen.getByLabelText("Where each record came from"),
    ).toHaveTextContent("SIMULATED bank statement");
  });
  it("names the record it trusted and why", () => {
    render(
      <ReconcilePanel
        reconciliation={recon}
        businessId="taxi"
        onReconciled={noop}
      />,
    );
    const note = screen.getByTestId("record-of-truth");
    expect(note).toHaveTextContent("Trusted: the bank.");
    expect(note).toHaveTextContent(recon.mismatches[0].record_reason!);
  });
  it("shows deposits in transit as timing, not errors", () => {
    render(
      <ReconcilePanel
        reconciliation={recon}
        businessId="taxi"
        onReconciled={noop}
      />,
    );
    const box = screen.getByTestId("in-transit");
    expect(box).toHaveTextContent("timing, not an error");
    expect(box).toHaveTextContent(recon.in_transit[0].ticker);
    expect(screen.getByText(/1 in transit/)).toBeVisible();
  });
  it("drops the simulated badge only when every leg is live", () => {
    const live = { ...recon, simulated: false };
    render(
      <ReconcilePanel
        reconciliation={live}
        businessId="taxi"
        onReconciled={noop}
      />,
    );
    const panel = screen.getByRole("region", { name: "Reconciliation" });
    expect(within(panel).queryByText("Simulated")).toBeNull();
  });
});

describe("Kalshi demo order on the hedge card", () => {
  const order = example<NonNullable<Hedge["venue_order"]>>("venue_order.json");
  it("shows a partial fill as fake money and flags the difference from the books", () => {
    render(<VenueOrderLine order={order} />);
    const line = screen.getByTestId("venue-order");
    expect(line).toHaveTextContent("Kalshi demo · fake money");
    expect(line).toHaveTextContent("Partly filled 300 of 420 at 50¢");
    expect(line).toHaveTextContent("reconciliation will flag it");
  });
  it("says why an order was skipped", () => {
    render(
      <VenueOrderLine
        order={{
          ...order,
          status: "skipped",
          filled: 0,
          avg_price: null,
          differs_from_booked: false,
          reason: "not listed on demo",
        }}
      />,
    );
    expect(screen.getByTestId("venue-order")).toHaveTextContent(
      "Not placed · not listed on demo",
    );
  });
});
