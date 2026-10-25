import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { LedgerTab, ReconcilePanel } from "@/components/LedgerTab";
import type { Ledger } from "@/lib/types";
import ledgerJson from "@/fixtures/ledger_with_mismatch.json";
const api = "http://localhost:8000";
const ledger = structuredClone(ledgerJson) as Ledger;
const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("C7-A28 reconciliation mismatch", () => {
  it("highlights the flagged row with the three sources side by side", () => {
    render(
      <ReconcilePanel
        reconciliation={ledger.reconciliation}
        businessId="taxi"
        onReconciled={async () => {}}
      />,
    );
    const table = screen.getByRole("table");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual([
      "Payout",
      "Expected",
      "Kalshi ledger",
      "Bank (simulated)",
      "Result",
    ]);
    const row = screen.getByTestId("mismatch-row");
    expect(row).toHaveClass("mismatch");
    expect(within(row).getByText("KXRAINNYC-26OCT16")).toBeVisible();
    expect(within(row).getAllByText("$60")).toHaveLength(2);
    expect(within(row).getByText("$58.95")).toBeVisible();
    expect(within(row).getByText("⚠ Flagged · −$1.05")).toBeVisible();
  });
  it("shows the explanation and the owner question", () => {
    render(
      <ReconcilePanel
        reconciliation={ledger.reconciliation}
        businessId="taxi"
        onReconciled={async () => {}}
      />,
    );
    const note = screen.getByRole("note", {
      name: "Flagged payout KXRAINNYC-26OCT16",
    });
    expect(
      within(note).getByText(ledger.reconciliation!.mismatches[0].explanation),
    ).toBeVisible();
    expect(
      within(note).getByText(ledger.reconciliation!.mismatches[0].question),
    ).toBeVisible();
    expect(within(note).getByText("Question for you:")).toBeVisible();
  });
  it("POSTs reconcile on click then refetches", async () => {
    let posted = 0;
    server.use(
      http.post(`${api}/businesses/taxi/reconcile`, () => {
        posted++;
        return HttpResponse.json(ledger.reconciliation);
      }),
    );
    const onReconciled = vi.fn(async () => {});
    render(
      <ReconcilePanel
        reconciliation={null}
        businessId="taxi"
        onReconciled={onReconciled}
      />,
    );
    expect(screen.getByText(/Not reconciled yet/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Run reconciliation" }));
    await waitFor(() => expect(onReconciled).toHaveBeenCalled());
    expect(posted).toBe(1);
  });
  it("shows the 409 message when nothing has settled", async () => {
    server.use(
      http.post(`${api}/businesses/taxi/reconcile`, () =>
        HttpResponse.json(
          {
            error: {
              code: "nothing_to_reconcile",
              message:
                "No hedge has settled yet, so there is nothing to reconcile.",
              detail: null,
            },
          },
          { status: 409 },
        ),
      ),
    );
    render(
      <ReconcilePanel
        reconciliation={null}
        businessId="taxi"
        onReconciled={async () => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Run reconciliation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No hedge has settled yet",
    );
  });
  it("lists ledger entries with postings", () => {
    render(
      <LedgerTab
        ledger={ledger}
        businessId="taxi"
        onReconciled={async () => {}}
      />,
    );
    const entries = screen.getByRole("region", { name: "Ledger entries" });
    expect(within(entries).getAllByRole("row")).toHaveLength(
      ledger.entries.length + 1,
    );
    expect(within(entries).getByText("Premium paid")).toBeVisible();
    expect(within(entries).getByText("−$66.47")).toBeVisible();
  });
});
