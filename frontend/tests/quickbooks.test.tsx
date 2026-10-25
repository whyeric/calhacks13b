// QuickBooks Online: connect in the upload drawer, pull revenue and research, and the
// "What you're committed to" panel. The backend is mocked with msw against the agreed
// contract (fixtures/quickbooks_*.json).
import { useEffect } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
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
import {
  DemoDesk,
  DemoUploadDrawer,
  useDemo,
  type DemoUpload,
} from "@/components/DemoDesk";
import type { QuickBooksResearch, QuickBooksStatus } from "@/lib/types";
import connectedFixture from "@/fixtures/quickbooks_status_connected.json";
import qboResearchFixture from "@/fixtures/quickbooks_research.json";

const api = "http://localhost:8000";
const connected = connectedFixture as QuickBooksStatus;
const qboResearch = qboResearchFixture as QuickBooksResearch;
const disconnected = (mode: "demo" | "live"): QuickBooksStatus => ({
  mode,
  connected: false,
  company_name: null,
  realm_id: null,
  connected_at: null,
  synthetic: mode === "demo",
});
const apiError = (status: number, code: string, message: string) =>
  HttpResponse.json({ error: { code, message, detail: {} } }, { status });

const calls: string[] = [];
const server = setupServer(
  http.get(`${api}/integrations/quickbooks/status`, () =>
    HttpResponse.json(disconnected("demo")),
  ),
  http.post(`${api}/integrations/quickbooks/connect`, () =>
    HttpResponse.json({ status: connected, authorize_url: null }),
  ),
  http.post(`${api}/integrations/quickbooks/disconnect`, () =>
    HttpResponse.json(disconnected("demo")),
  ),
  http.post(`${api}/integrations/quickbooks/research`, ({ request }) => {
    calls.push(request.url);
    return HttpResponse.json(qboResearch);
  }),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  calls.length = 0;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
afterAll(() => server.close());

const drawer = (props: Partial<Parameters<typeof DemoUploadDrawer>[0]> = {}) =>
  render(
    <DemoUploadDrawer open onClose={() => {}} onStart={() => {}} {...props} />,
  );

describe("QuickBooks connect (upload drawer)", () => {
  it("is the primary path above the CSV upload, and demo connect shows the synthetic company", async () => {
    const onStart = vi.fn();
    drawer({ onStart });
    const card = screen.getByTestId("qbo-connect");
    const connect = within(card).getByRole("button", {
      name: "Connect QuickBooks",
    });
    // QuickBooks comes first; the CSV form is the fallback below it.
    const csv = screen.getByRole("button", { name: "Upload and research" });
    expect(
      connect.compareDocumentPosition(csv) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText("Or upload a CSV")).toBeVisible();
    expect(
      await within(card).findByText(/Demo mode connects a synthetic company/),
    ).toBeVisible();

    fireEvent.click(connect);
    expect(
      await within(card).findByText("Hudson Bike Co. (SYNTHETIC)"),
    ).toBeVisible();
    expect(within(card).getByTestId("qbo-synthetic")).toHaveTextContent(
      "Synthetic demo data",
    );
    expect(within(card).getByTestId("qbo-mode")).toHaveTextContent("Demo mode");
    expect(
      within(card).getByText(/Connected to QuickBooks Online/),
    ).toBeVisible();

    fireEvent.click(
      within(card).getByRole("button", { name: "Pull revenue and research" }),
    );
    expect(onStart).toHaveBeenCalledWith({
      name: "Hudson Bike Co. (SYNTHETIC)",
      kind: "Bike rental",
      source: "quickbooks",
    });

    fireEvent.click(within(card).getByRole("button", { name: "Disconnect" }));
    expect(
      await within(card).findByRole("button", { name: "Connect QuickBooks" }),
    ).toBeVisible();
    expect(within(card).queryByText("Hudson Bike Co. (SYNTHETIC)")).toBeNull();
  });

  it("live mode sends the browser to Intuit's authorize_url", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const authorize =
      "https://appcenter.intuit.com/connect/oauth2?client_id=abc&state=xyz";
    server.use(
      http.get(`${api}/integrations/quickbooks/status`, () =>
        HttpResponse.json(disconnected("live")),
      ),
      http.post(`${api}/integrations/quickbooks/connect`, () =>
        HttpResponse.json({
          status: disconnected("live"),
          authorize_url: authorize,
        }),
      ),
    );
    drawer();
    expect(await screen.findByTestId("qbo-mode")).toHaveTextContent("Live");
    fireEvent.click(screen.getByRole("button", { name: "Connect QuickBooks" }));
    expect(
      await screen.findByRole("button", { name: "Opening QuickBooks…" }),
    ).toBeDisabled();
    expect(assign).toHaveBeenCalledWith(authorize);
  });

  it("shows a readable message when QuickBooks is unavailable (502)", async () => {
    server.use(
      http.post(`${api}/integrations/quickbooks/connect`, () =>
        apiError(502, "quickbooks_unavailable", "Intuit returned 503"),
      ),
    );
    drawer();
    fireEvent.click(screen.getByRole("button", { name: "Connect QuickBooks" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "QuickBooks didn’t answer just now. Please try again in a minute.",
    );
    expect(
      screen.getByRole("button", { name: "Connect QuickBooks" }),
    ).toBeEnabled();
  });

  it("after ?qbo=connected it reads the connection; ?qbo=error shows an error", async () => {
    server.use(
      http.get(`${api}/integrations/quickbooks/status`, () =>
        HttpResponse.json(connected),
      ),
    );
    const { unmount } = drawer({ quickBooksReturn: "connected" });
    expect(
      await screen.findByText("Hudson Bike Co. (SYNTHETIC)"),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Pull revenue and research" }),
    ).toBeEnabled();
    unmount();

    server.use(
      http.get(`${api}/integrations/quickbooks/status`, () =>
        HttpResponse.json(disconnected("live")),
      ),
    );
    drawer({ quickBooksReturn: "error" });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "QuickBooks didn’t finish connecting",
    );
    expect(
      await screen.findByRole("button", { name: "Connect QuickBooks" }),
    ).toBeVisible();
  });
});

// --- Pull revenue and research → the shared report view ---------------------
const qboUpload: DemoUpload = {
  name: "Hudson Bike Co. (SYNTHETIC)",
  kind: "Bike rental",
  source: "quickbooks",
};
function Harness() {
  const demo = useDemo();
  const { start, upload, skip } = demo;
  useEffect(() => start(qboUpload), [start]);
  useEffect(() => {
    if (upload) skip();
  }, [upload, skip]);
  return <DemoDesk demo={demo} onRemoved={() => {}} />;
}
const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 60));
  });

describe("QuickBooks research report", () => {
  it("renders the report with the QuickBooks header and the commitments panel", async () => {
    render(<Harness />);
    expect(
      await screen.findByTestId("research-row-rain", {}, { timeout: 4000 }),
    ).toBeVisible();
    await settle();
    expect(calls).toEqual([
      `${api}/integrations/quickbooks/research?name=Hudson%20Bike%20Co.%20(SYNTHETIC)`,
    ]);
    expect(
      within(screen.getByTestId("demo-research")).getByRole("heading", {
        level: 2,
      }),
    ).toHaveTextContent(
      "Hudson Bike Co. (SYNTHETIC) · QuickBooks Online · 1,004 days · 2024-01-01 to 2026-09-30",
    );
    expect(screen.getByTestId("qbo-source")).toHaveTextContent(
      `Synthetic demo data Revenue: ${qboResearch.revenue_source}`,
    );
    expect(screen.getByRole("button", { name: "Clear report" })).toBeVisible();

    const panel = screen.getByTestId("qbo-commitments");
    expect(
      within(panel).getByRole("heading", { name: "What you’re committed to" }),
    ).toBeVisible();
    expect(panel).toHaveTextContent("From QuickBooks Online, as of 2026-10-25");
    expect(within(panel).getByText("Synthetic demo data")).toBeVisible();
    // Totals are the API's strings, formatted (never summed in the browser).
    expect(within(panel).getByTestId("committed-spend")).toHaveTextContent(
      "$20,582.07",
    );
    expect(within(panel).getByTestId("expected-revenue")).toHaveTextContent(
      "$9,265",
    );
    expect(within(panel).getByTestId("inventory-value")).toHaveTextContent(
      "$26,982.50",
    );
    // Sorted by due date, undated last.
    const ids = (label: string) =>
      within(within(panel).getByRole("list", { name: label }))
        .getAllByRole("listitem")
        .map((li) => li.getAttribute("data-testid"));
    expect(ids("Unpaid bills")).toEqual([
      "commitment-bill_8814",
      "commitment-bill_8813",
      "commitment-bill_8812",
      "commitment-bill_8815",
    ]);
    expect(ids("Open purchase orders")).toEqual([
      "commitment-po_1042",
      "commitment-po_1041",
      "commitment-po_1043",
    ]);
    expect(ids("Pending estimates").at(-1)).toBe("commitment-est_2210");
    expect(within(panel).getByTestId("commitment-est_2210")).toHaveTextContent(
      "no due date",
    );
    expect(within(panel).getByTestId("commitment-po_1042")).toHaveTextContent(
      "Quality Bicycle Products",
    );
    expect(within(panel).getByTestId("commitment-po_1042")).toHaveTextContent(
      "$2,315.40due 2026-11-05",
    );
    expect(within(panel).getByTestId("inventory-item_01")).toHaveTextContent(
      "FX2-RNT · 38 on hand × $649",
    );
    expect(within(panel).getByTestId("inventory-item_01")).toHaveTextContent(
      "$24,662",
    );
  });

  it("shows a readable error when QuickBooks isn't connected (409)", async () => {
    server.use(
      http.post(`${api}/integrations/quickbooks/research`, () =>
        apiError(409, "not_connected", "not connected"),
      ),
    );
    render(<Harness />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "QuickBooks isn’t connected. Connect it, then try again.",
    );
    expect(screen.queryByTestId("research-row-rain")).toBeNull();
    expect(screen.queryByTestId("qbo-commitments")).toBeNull();
  });

  it("passes a 422 research error through as the API's message", async () => {
    server.use(
      http.post(`${api}/integrations/quickbooks/research`, () =>
        apiError(
          422,
          "too_short",
          "Need at least 540 open days inside the weather record; found 28.",
        ),
      ),
    );
    render(<Harness />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Need at least 540 open days",
    );
  });
});
