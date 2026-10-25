import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
import { SWRConfig } from "swr";
import { SettingsDrawer, SettingsForm } from "@/components/SettingsDrawer";
import type { Hedge, Settings } from "@/lib/types";
import settingsJson from "@/fixtures/settings.json";
import hedgesJson from "@/fixtures/hedges_mixed.json";
const api = "http://localhost:8000";
const settings = structuredClone(settingsJson) as Settings;
const hedges = structuredClone(hedgesJson) as unknown as Hedge[];
let put: Record<string, unknown>;
const server = setupServer(
  http.get(`${api}/businesses/:id/settings`, () => HttpResponse.json(settings)),
  http.put(`${api}/businesses/:id/settings`, async ({ request }) => {
    put = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(put);
  }),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
const field = (name: RegExp) => screen.getByRole("textbox", { name });
const save = () =>
  screen.getByRole("button", { name: "Save and re-check hedges" });

describe("C7-A19 settings validation", () => {
  it.each([
    [/Most we’ll overpay/, "", "Required."],
    [/Most we’ll overpay/, "1.5", "Enter a number from 0 to 1"],
    [/Most we’ll overpay/, "-0.1", "Enter a number from 0 to 1"],
    [/Weekly budget/, "abc", "Enter a dollar amount"],
    [/Weekly budget/, "  ", "Required."],
  ])("disables Save for %s = %j", (name, value, message) => {
    render(<SettingsForm initial={settings} onSave={async () => {}} />);
    expect(save()).toBeEnabled();
    fireEvent.change(field(name), { target: { value } });
    expect(save()).toBeDisabled();
    expect(screen.getByText(new RegExp(message))).toBeVisible();
  });
  it("sends every value as a string, unchanged otherwise", async () => {
    const onSave = vi.fn(async () => {});
    render(<SettingsForm initial={settings} onSave={onSave} />);
    fireEvent.change(field(/Most we’ll overpay/), {
      target: { value: "0.40" },
    });
    fireEvent.click(save());
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave).toHaveBeenCalledWith({
      weekly_budget: "250.00",
      thresholds: {
        min_size_usd: "150.00",
        min_support: "10",
        overpay_max: "0.40",
        cost_ratio_max: "0.35",
        fill_decline: "0.5",
        fill_full: "1.0",
        max_slip: "0.05",
        basis_r2_min: "0.5",
        max_tool_calls: "12",
      },
    });
  });
});

describe("settings drawer save", () => {
  it("PUTs, refetches hedges and lists the decisions that flipped", async () => {
    const flipped = hedges.map((row) =>
      row.id === "hdg_03"
        ? { ...row, status: "pending_approval" as const }
        : row,
    );
    const onSaved = vi.fn(async () => flipped);
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <SettingsDrawer
          businessId="taxi"
          open
          onClose={() => {}}
          hedges={hedges}
          onSaved={onSaved}
        />
      </SWRConfig>,
    );
    fireEvent.change(
      await screen.findByRole("textbox", { name: /Most protection may cost/ }),
      {
        target: { value: "0.40" },
      },
    );
    fireEvent.click(save());
    expect(await screen.findByText("1 decision changed")).toBeVisible();
    expect(put).toMatchObject({ thresholds: { cost_ratio_max: "0.40" } });
    expect(onSaved).toHaveBeenCalledOnce();
    expect(screen.getByText("Declined")).toHaveClass("flip-from");
    expect(screen.getByText("Over budget · needs approval")).toBeVisible();
  });
});
