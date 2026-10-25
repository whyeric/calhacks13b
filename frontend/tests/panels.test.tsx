import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { SWRConfig } from "swr";
import Home from "@/app/page";
import businesses from "@/fixtures/businesses.json";
import taxi from "@/fixtures/analyze_taxi.json";
import restaurant from "@/fixtures/analyze_restaurant.json";
import hedgesJson from "@/fixtures/hedges_mixed.json";
import logs from "@/fixtures/decisions.json";
import backtest from "@/fixtures/backtest_taxi.json";
import ledger from "@/fixtures/ledger_with_mismatch.json";
import benchmark from "@/fixtures/recon_benchmark.json";
import chat from "@/fixtures/chat_reply.json";
import settings from "@/fixtures/settings.json";
import { resetMock, mockRequest } from "@/lib/mock";
import type { Hedge, LogEntry, Settings } from "@/lib/types";
const api = "http://localhost:8000";
const health = { status: "ok", offline: true, anthropic: "fallback" };
let requests: string[] = [];
const server = setupServer(
  http.get(`${api}/businesses`, () => HttpResponse.json(businesses)),
  http.post(`${api}/businesses/:id/analyze`, ({ params }) =>
    HttpResponse.json(params.id === "taxi" ? taxi : restaurant),
  ),
  http.get(`${api}/businesses/:id/hedges`, () => HttpResponse.json(hedgesJson)),
  http.get(`${api}/businesses/:id/decisions`, () => HttpResponse.json(logs)),
  http.get(`${api}/businesses/:id/backtest`, () => HttpResponse.json(backtest)),
  http.get(`${api}/businesses/:id/ledger`, () => HttpResponse.json(ledger)),
  http.get(`${api}/benchmarks/reconciliation`, () =>
    HttpResponse.json(benchmark),
  ),
  http.get(`${api}/businesses/:id/settings`, () => HttpResponse.json(settings)),
  http.post(`${api}/businesses/:id/chat`, () => HttpResponse.json(chat)),
  http.get(`${api}/health`, () => HttpResponse.json(health)),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  requests = [];
});
afterAll(() => server.close());
server.events.on("request:start", ({ request }) => {
  requests.push(`${request.method} ${new URL(request.url).pathname}`);
});
const mount = () =>
  render(
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
      }}
    >
      <Home />
    </SWRConfig>,
  );

describe("sample week banner (M3 carry-over)", () => {
  it("is per business: follows /health sample_businesses", async () => {
    server.use(
      http.get(`${api}/health`, () =>
        HttpResponse.json({
          ...health,
          sample_week: true,
          sample_businesses: ["taxi"],
        }),
      ),
    );
    mount();
    expect(await screen.findByText("Sample week")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Your business"), {
      target: { value: "restaurant" },
    });
    await screen.findByText("−$1,240");
    expect(screen.queryByText("Sample week")).not.toBeInTheDocument();
  });
  it("sample_week alone without the business listed shows no banner", async () => {
    server.use(
      http.get(`${api}/health`, () =>
        HttpResponse.json({ ...health, sample_week: true }),
      ),
    );
    mount();
    await screen.findAllByTestId("hedge-card");
    await screen.findByTestId("backtest-panel");
    expect(screen.queryByText("Sample week")).not.toBeInTheDocument();
  });
  it("shows when a hedge carries sample_week: true", async () => {
    server.use(
      http.get(`${api}/businesses/:id/hedges`, () =>
        HttpResponse.json(
          hedgesJson.map((row) => ({ ...row, sample_week: true })),
        ),
      ),
    );
    mount();
    expect(await screen.findByText("Sample week")).toBeVisible();
  });
  it("treats a missing or false flag as live", async () => {
    server.use(
      http.get(`${api}/health`, () =>
        HttpResponse.json({
          ...health,
          sample_week: false,
          sample_businesses: [],
        }),
      ),
    );
    mount();
    await screen.findAllByTestId("hedge-card");
    await screen.findByTestId("backtest-panel");
    expect(screen.queryByText("Sample week")).not.toBeInTheDocument();
  });
  it("a failing /health never blocks the page", async () => {
    server.use(
      http.get(`${api}/health`, () => new HttpResponse(null, { status: 500 })),
    );
    mount();
    await screen.findAllByTestId("hedge-card");
    expect(screen.queryByText("Sample week")).not.toBeInTheDocument();
  });
});

describe("bottom panels", () => {
  it("409 backtest_not_ready shows an honest empty state", async () => {
    server.use(
      http.get(`${api}/businesses/:id/backtest`, () =>
        HttpResponse.json(
          {
            error: {
              code: "backtest_not_ready",
              message: "The backtest has not been run for this business yet.",
              detail: null,
            },
          },
          { status: 409 },
        ),
      ),
    );
    mount();
    expect(await screen.findByText("No backtest yet.")).toBeVisible();
    expect(screen.queryByText(/Weekly income swings/)).not.toBeInTheDocument();
  });
  it("ledger is fetched on tab open and shows the planted mismatch", async () => {
    mount();
    await screen.findByTestId("backtest-panel");
    expect(requests).not.toContain("GET /businesses/taxi/ledger");
    fireEvent.click(screen.getByRole("tab", { name: /Books/ }));
    expect(await screen.findByTestId("mismatch-row")).toBeVisible();
    expect(requests).toContain("GET /businesses/taxi/ledger");
    expect(screen.getByText(/Did you authorize the \$1.05 fee/)).toBeVisible();
  });
  it("Books tab shows the planted-error benchmark scorecard, labeled simulated", async () => {
    mount();
    await screen.findByTestId("backtest-panel");
    fireEvent.click(screen.getByRole("tab", { name: /Books/ }));
    const card = await screen.findByTestId("recon-benchmark");
    expect(requests).toContain("GET /benchmarks/reconciliation");
    expect(within(card).getByText("Caught 17 of 17")).toBeVisible();
    expect(card).toHaveTextContent("0 false flags on 7 traps");
    expect(within(card).getByText(/Simulated/)).toBeVisible();
    expect(within(card).getAllByTestId("benchmark-case")).toHaveLength(24);
    expect(within(card).getAllByText("Transposed digits")).toHaveLength(4);
  });
  it("C7-A16 switching business refetches backtest/ledger and clears chat", async () => {
    mount();
    await screen.findByTestId("backtest-panel");
    fireEvent.click(screen.getByRole("tab", { name: /Books/ }));
    await screen.findByTestId("mismatch-row");
    fireEvent.click(screen.getByRole("button", { name: /Ask/ }));
    fireEvent.change(screen.getByLabelText("Your question"), {
      target: { value: "Why?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByTestId("chat-desk");
    fireEvent.change(screen.getByLabelText("Your business"), {
      target: { value: "restaurant" },
    });
    await waitFor(() =>
      expect(requests).toEqual(
        expect.arrayContaining([
          "POST /businesses/restaurant/analyze",
          "GET /businesses/restaurant/hedges",
          "GET /businesses/restaurant/decisions",
          "GET /businesses/restaurant/backtest",
        ]),
      ),
    );
    expect(screen.queryByTestId("chat-desk")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chat-owner")).not.toBeInTheDocument();
  });
});

describe("settings flip through the page", () => {
  it("PUT re-runs server rules, page refetches and shows the flip", async () => {
    let saved = false;
    server.use(
      http.get(`${api}/businesses/:id/hedges`, () =>
        HttpResponse.json(
          hedgesJson.map((row) =>
            saved && row.id === "hdg_03"
              ? { ...row, status: "pending_approval" }
              : row,
          ),
        ),
      ),
      http.put(`${api}/businesses/:id/settings`, async ({ request }) => {
        saved = true;
        return HttpResponse.json(await request.json());
      }),
    );
    mount();
    await screen.findAllByTestId("hedge-card");
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const drawer = await screen.findByRole("dialog", { name: "Desk settings" });
    fireEvent.change(
      await within(drawer).findByRole("textbox", {
        name: /Most we’ll overpay/,
      }),
      { target: { value: "0.40" } },
    );
    fireEvent.click(
      within(drawer).getByRole("button", { name: "Save and re-check hedges" }),
    );
    expect(await within(drawer).findByText("1 decision changed")).toBeVisible();
    expect(requests).toContain("PUT /businesses/taxi/settings");
    expect(
      requests.filter((r) => r === "GET /businesses/taxi/hedges").length,
    ).toBeGreaterThan(1);
    expect(
      requests.filter((r) => r === "POST /businesses/taxi/analyze").length,
    ).toBeGreaterThan(1);
  });
});

describe("mock server settings re-check", () => {
  it("raising both thresholds flips the declined hedge; restoring flips back", async () => {
    resetMock();
    const path = "/businesses/taxi";
    const base = await mockRequest<Settings>("GET", `${path}/settings`);
    const status = async () =>
      (await mockRequest<Hedge[]>("GET", `${path}/hedges`)).map(
        (row) => row.status,
      );
    expect(await status()).toEqual([
      "proposed",
      "declined",
      "pending_approval",
    ]);
    await mockRequest("PUT", `${path}/settings`, {
      ...base,
      thresholds: {
        ...base.thresholds,
        overpay_max: "0.40",
        cost_ratio_max: "0.40",
      },
    });
    expect(await status()).toEqual([
      "proposed",
      "pending_approval",
      "pending_approval",
    ]);
    const log = await mockRequest<LogEntry[]>("GET", `${path}/decisions`);
    expect(log.at(-1)?.kind).toBe("threshold_changed");
    await mockRequest("PUT", `${path}/settings`, base);
    expect(await status()).toEqual([
      "proposed",
      "declined",
      "pending_approval",
    ]);
  });
});
