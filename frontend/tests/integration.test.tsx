import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, expect, it } from "vitest";
import { http, HttpResponse, delay } from "msw";
import { setupServer } from "msw/node";
import { SWRConfig } from "swr";
import Home from "@/app/page";
import businesses from "@/fixtures/businesses.json";
import taxi from "@/fixtures/analyze_taxi.json";
import restaurant from "@/fixtures/analyze_restaurant.json";
import hedges from "@/fixtures/hedges_mixed.json";
import logs from "@/fixtures/decisions.json";
import backtest from "@/fixtures/backtest_taxi.json";
const api = "http://localhost:8000";
const server = setupServer(
  http.get(`${api}/businesses`, () => HttpResponse.json(businesses)),
  http.post(`${api}/businesses/:id/analyze`, ({ params }) =>
    HttpResponse.json(params.id === "taxi" ? taxi : restaurant),
  ),
  http.get(`${api}/businesses/:id/hedges`, () => HttpResponse.json(hedges)),
  http.get(`${api}/businesses/:id/decisions`, () => HttpResponse.json(logs)),
  http.get(`${api}/businesses/:id/backtest`, () => HttpResponse.json(backtest)),
  http.get(`${api}/health`, () =>
    HttpResponse.json({ status: "ok", offline: true, anthropic: "fallback" }),
  ),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
function mount() {
  return render(
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
}
it("C7-A17 late taxi response cannot appear under restaurant", async () => {
  server.use(
    http.post(`${api}/businesses/:id/analyze`, async ({ params }) => {
      if (params.id === "taxi") await delay(200);
      return HttpResponse.json(params.id === "taxi" ? taxi : restaurant);
    }),
  );
  mount();
  await screen.findByLabelText("Your business");
  fireEvent.change(screen.getByLabelText("Your business"), {
    target: { value: "restaurant" },
  });
  expect(await screen.findByText("−$1,240")).toBeVisible();
  await delay(250);
  expect(
    screen.queryByText("Revenue rises on event days"),
  ).not.toBeInTheDocument();
});
it("C7-A20 each region has its own loading skeleton", async () => {
  server.use(
    http.post(`${api}/businesses/:id/analyze`, async () => {
      await delay(200);
      return HttpResponse.json(taxi);
    }),
    http.get(`${api}/businesses/:id/hedges`, async () => {
      await delay(200);
      return HttpResponse.json(hedges);
    }),
    http.get(`${api}/businesses/:id/decisions`, async () => {
      await delay(200);
      return HttpResponse.json(logs);
    }),
    http.get(`${api}/businesses/:id/backtest`, async () => {
      await delay(200);
      return HttpResponse.json(backtest);
    }),
  );
  mount();
  await screen.findByLabelText("Your business");
  expect(screen.getAllByLabelText("Loading region")).toHaveLength(4);
  await screen.findByText("Revenue rises on event days");
});
it("C7-A21 empty state has no invalid numeric tokens", async () => {
  server.use(
    http.get(`${api}/businesses/:id/hedges`, () => HttpResponse.json([])),
    http.get(`${api}/businesses/:id/decisions`, () => HttpResponse.json([])),
  );
  const { container } = mount();
  expect(
    await screen.findByText("No hedges this week. Run the desk."),
  ).toBeVisible();
  expect(container.textContent).not.toMatch(/undefined|NaN|\$null/);
});
it("C7-A22 failed region retries while other regions render", async () => {
  let calls = 0;
  server.use(
    http.post(`${api}/businesses/:id/analyze`, () => {
      calls++;
      return calls === 1
        ? new HttpResponse(null, { status: 500 })
        : HttpResponse.json(taxi);
    }),
  );
  mount();
  await screen.findByRole("alert");
  await screen.findAllByTestId("hedge-card");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("Revenue rises on event days")).toBeVisible();
  expect(calls).toBe(2);
});
it("C7-A14 approval refetches budget, hedges and decisions from server", async () => {
  const counts = { businesses: 0, hedges: 0, decisions: 0 };
  let approved = false;
  server.use(
    http.get(`${api}/businesses`, () => {
      counts.businesses++;
      return HttpResponse.json(businesses);
    }),
    http.get(`${api}/businesses/:id/hedges`, () => {
      counts.hedges++;
      return HttpResponse.json(
        hedges.map((row, index) =>
          approved && index === 0 ? { ...row, status: "approved" } : row,
        ),
      );
    }),
    http.get(`${api}/businesses/:id/decisions`, () => {
      counts.decisions++;
      return HttpResponse.json(logs);
    }),
    http.post(`${api}/hedges/:id/approve`, async ({ request }) => {
      expect(await request.json()).toEqual({ actor: "owner" });
      approved = true;
      return HttpResponse.json({});
    }),
  );
  mount();
  await screen.findAllByTestId("hedge-card");
  fireEvent.click(screen.getAllByRole("button", { name: "Approve" })[0]);
  await waitFor(() =>
    expect(
      screen.getAllByText("Approved", { exact: true }).length,
    ).toBeGreaterThan(0),
  );
  expect(counts.businesses).toBeGreaterThan(1);
  expect(counts.hedges).toBeGreaterThan(1);
  expect(counts.decisions).toBeGreaterThan(1);
});
it("C7-A20 polls run endpoint until done before refreshing", async () => {
  let polls = 0;
  server.use(
    http.post(`${api}/businesses/:id/desk/run`, () =>
      HttpResponse.json({ run_id: "run1" }),
    ),
    http.get(`${api}/runs/run1`, () => {
      polls++;
      return HttpResponse.json({ status: polls === 1 ? "running" : "done" });
    }),
  );
  mount();
  await screen.findByLabelText("Your business");
  fireEvent.click(screen.getByRole("button", { name: /Run desk/ }));
  expect(screen.getByRole("button", { name: "Running…" })).toBeDisabled();
  await waitFor(
    () =>
      expect(screen.getByRole("button", { name: /Run desk/ })).toBeEnabled(),
    { timeout: 3000 },
  );
  expect(polls).toBe(2);
});
