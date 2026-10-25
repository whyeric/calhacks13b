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
import { HedgeCard, HedgeList } from "@/components/HedgeCard";
import { PlayoffCard, groupHedges, teamName } from "@/components/PlayoffCard";
import { ExposureList } from "@/components/ExposureList";
import { Header } from "@/components/Header";
import Research from "@/app/research/page";
import { FINDINGS, DECLINED } from "@/lib/research";
import { mockRequest, resetMock } from "@/lib/mock";
import playoffJson from "@/fixtures/hedges_playoff.json";
import unstableJson from "@/fixtures/hedge_declined_unstable.json";
import exposureJson from "@/fixtures/exposure_playoff_home.json";
import mixedJson from "@/fixtures/hedges_mixed.json";
import businesses from "@/fixtures/businesses.json";
import type { Business, ExposureRow, Hedge } from "@/lib/types";

const legs = () => structuredClone(playoffJson) as unknown as Hedge[];
const exposure = () => structuredClone(exposureJson) as unknown as ExposureRow;
const unstable = () => structuredClone(unstableJson) as unknown as Hedge;
const mixed = () => structuredClone(mixedJson) as unknown as Hedge[];
const noop = async () => {};

const api = "http://localhost:8000";
let posted: string[] = [];
const server = setupServer(
  http.post(`${api}/hedges/:id/:action`, async ({ params, request }) => {
    const body = (await request.json()) as { actor?: string };
    posted.push(`${params.action} ${params.id} ${body.actor}`);
    return HttpResponse.json({});
  }),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  posted = [];
});
afterAll(() => server.close());

describe("playoff season protection card", () => {
  it("groups the legs into one card with stake, legs and API total premium", () => {
    render(
      <PlayoffCard legs={legs()} exposure={exposure()} onChanged={noop} />,
    );
    const card = screen.getByTestId("playoff-card");
    expect(within(card).getByText("Playoff season protection")).toBeVisible();
    expect(card).toHaveTextContent(
      "Each extra Knicks home playoff game brings about $604",
    );
    expect(card).toHaveTextContent("about 6.6 home games expected");
    expect(within(card).getByText("Estimated")).toBeVisible();
    expect(card).toHaveTextContent(
      "If the Knicks go out early, these pay you back for the home games you didn’t get.",
    );
    const table = within(card).getByRole("table");
    const rows = within(table).getAllByRole("row");
    // header + 3 legs + total
    expect(rows).toHaveLength(5);
    expect(rows[1]).toHaveTextContent("Knicks miss the playoffs");
    expect(rows[1]).toHaveTextContent("NO · KXNBAPLAYOFF-27-NYK");
    expect(rows[1]).toHaveTextContent("9¢");
    expect(rows[1]).toHaveTextContent("1,600");
    expect(rows[1]).toHaveTextContent("$153.17");
    expect(rows[2]).toHaveTextContent("KXNBAEAST-27-NYK");
    expect(rows[3]).toHaveTextContent("KXNBA-27-NYK");
    expect(rows[4]).toHaveTextContent("Total premium$1,013.27");
    expect(card).toHaveTextContent(/Dollars assume a \$35 average check/);
  });

  it("degrades when the exposure, labels and total are missing", () => {
    const bare = legs().map((leg) => {
      const row = { ...leg } as Record<string, unknown>;
      delete row.leg_label;
      delete row.group_total_premium;
      return row as unknown as Hedge;
    });
    render(<PlayoffCard legs={bare} onChanged={noop} />);
    const card = screen.getByTestId("playoff-card");
    expect(card).not.toHaveTextContent(/undefined|NaN|null/);
    expect(card).not.toHaveTextContent("Total premium");
    expect(card).not.toHaveTextContent("brings about");
    expect(card).toHaveTextContent(
      "Will the New York Knicks make the 2027 NBA playoffs?",
    );
  });

  it("approve all posts an owner approval for every open leg", async () => {
    const onChanged = vi.fn(async () => {});
    render(<PlayoffCard legs={legs()} onChanged={onChanged} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve all" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(posted).toEqual([
      "approve hdg_po_1 owner",
      "approve hdg_po_2 owner",
      "approve hdg_po_3 owner",
    ]);
  });

  it("team name comes from the ticker, with a neutral fallback", () => {
    expect(teamName(legs())).toBe("Knicks");
    expect(teamName([{ ...legs()[0], ticker: null }])).toBe("home team");
  });

  it("groupHedges keeps ordinary hedges separate and playoff legs together", () => {
    const items = groupHedges([...mixed(), ...legs()]);
    expect(items).toHaveLength(4);
    expect(Array.isArray(items[3]) && items[3]).toHaveLength(3);
    expect(groupHedges(mixed()).every((item) => !Array.isArray(item))).toBe(
      true,
    );
  });

  it("HedgeList renders one playoff card and counts it as one decision", () => {
    render(
      <HedgeList
        hedges={[...mixed(), ...legs()]}
        exposures={[exposure()]}
        onChanged={noop}
      />,
    );
    expect(screen.getAllByTestId("hedge-card")).toHaveLength(3);
    expect(screen.getAllByTestId("playoff-card")).toHaveLength(1);
    expect(screen.getByText("4 decisions")).toBeVisible();
  });
});

describe("unstable decline", () => {
  it("shows the plain-language reason and last year vs recent effect", () => {
    render(<HedgeCard hedge={unstable()} onChanged={noop} />);
    const card = screen.getByTestId("hedge-card");
    const reasons = within(card).getAllByRole("listitem")[0];
    expect(reasons).toHaveTextContent(
      "Not reliable: the effect didn’t hold up in recent months",
    );
    const compare = within(card).getByLabelText("Effect last year vs recent");
    expect(compare).toHaveTextContent("Last year−$1,240");
    expect(compare).toHaveTextContent("Recent months$128");
  });
  it("omits the comparison when the metric is missing", () => {
    const row = unstable();
    row.decision.checks = row.decision.checks.map((check) => ({
      ...check,
      metric: {},
    }));
    render(<HedgeCard hedge={row} onChanged={noop} />);
    expect(
      screen.queryByLabelText("Effect last year vs recent"),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByText(
        "Not reliable: the effect didn’t hold up in recent months",
      )[0],
    ).toBeVisible();
  });
});

describe("playoff_home exposure row", () => {
  it("shows the expected count, estimated badge and basis note", () => {
    render(<ExposureList exposures={[exposure()]} />);
    expect(screen.getByText("Playoff home game")).toBeVisible();
    expect(screen.getByText("$604")).toBeVisible();
    expect(
      screen.getByText(/Revenue per extra playoff home game/),
    ).toHaveTextContent("about 6.6 expected this season");
    expect(screen.getByText("Estimated")).toBeVisible();
    expect(screen.getByText(/Foot traffic within 0.5 km of MSG/)).toBeVisible();
  });
});

describe("mock mode", () => {
  it("serves the playoff legs and unstable decline for the bar only", async () => {
    resetMock();
    const bar = await mockRequest<Hedge[]>(
      "GET",
      "/businesses/restaurant/hedges",
    );
    expect(
      bar.filter((row) => row.exposure_id === "exp_playoff_home"),
    ).toHaveLength(3);
    expect(
      bar.some((row) => row.decision.reasons.includes("unstable" as never)),
    ).toBe(true);
    const taxi = await mockRequest<Hedge[]>("GET", "/businesses/taxi/hedges");
    expect(taxi).toHaveLength(3);
    const analyze = await mockRequest<{ exposures: ExposureRow[] }>(
      "POST",
      "/businesses/restaurant/analyze",
    );
    expect(analyze.exposures.map((row) => row.event)).toContain("playoff_home");
  });
});

describe("research page", () => {
  it("links from the header", () => {
    render(
      <Header
        businesses={businesses as Business[]}
        selectedId="taxi"
        onSelect={() => {}}
        onRun={() => {}}
        running={false}
      />,
    );
    expect(
      screen.getByRole("link", { name: "Why this works" }),
    ).toHaveAttribute("href", "/research");
  });
  it("presents findings, declines and sources on one page", () => {
    render(<Research />);
    expect(
      screen.getByRole("heading", { name: /We tested 40\+ hypotheses/ }),
    ).toBeVisible();
    const table = screen.getByRole("table", { name: /Every finding/ });
    expect(within(table).getAllByRole("row")).toHaveLength(FINDINGS.length + 1);
    expect(table).toHaveTextContent("+126%");
    expect(table).toHaveTextContent("+107%");
    expect(table).toHaveTextContent("−19.7%");
    for (const row of DECLINED)
      expect(screen.getByRole("heading", { name: row.title })).toBeVisible();
    expect(screen.getByText(/\+\$32 a day on the power bill/)).toBeVisible();
    expect(screen.getByText("−$2.9k")).toBeVisible();
    const sources = screen
      .getAllByRole("link")
      .map((link) => link.getAttribute("href") ?? "")
      .filter((href) => href.includes("/experiments/bar/"));
    expect(sources.length).toBeGreaterThan(8);
    sources.forEach((href) =>
      expect(href).toMatch(
        /^https:\/\/github\.com\/whyeric\/calhacks13b\/blob\/experiments\/bar\/experiments\/bar\//,
      ),
    );
    expect(document.body).not.toHaveTextContent(/undefined|NaN/);
  });
});
