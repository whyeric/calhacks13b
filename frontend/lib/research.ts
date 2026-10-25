// Findings from experiments/bar/*/RESULTS.md (branch experiments/bar). Static research
// copy, quoted from those files; nothing here is computed in the browser.
export const SOURCE_BASE =
  "https://github.com/whyeric/calhacks13b/blob/experiments/bar/experiments/bar";
export const source = (dir: string) => `${SOURCE_BASE}/${dir}/RESULTS.md`;

export type Finding = {
  id: string;
  event: string;
  measure: string;
  /** % change in the fit period and in the independent check, as printed in RESULTS.md. */
  fit: number;
  check: number;
  fitLabel: string;
  checkLabel: string;
  approx?: boolean;
  dir: string;
};

export const FINDINGS: Finding[] = [
  {
    id: "wrigley",
    event: "Cubs playoff home game",
    measure: "Bike-share trips within 450 m of Wrigley Field",
    fit: 126,
    check: 107,
    fitLabel: "2014–16",
    checkLabel: "2017",
    dir: "r6-wrigley",
  },
  {
    id: "rideshare",
    event: "Knicks/Rangers playoff home game",
    measure: "Taxi + Uber/Lyft driver earnings near MSG, 9 pm–1 am",
    fit: 39.8,
    check: 36.0,
    fitLabel: "2022–23",
    checkLabel: "2024–26",
    dir: "r5-mobility",
  },
  {
    id: "msg",
    event: "Knicks/Rangers playoff home game",
    measure: "Foot traffic at restaurants and bars within 0.5 km of MSG",
    fit: 5.7,
    check: 5.7,
    fitLabel: "2024–Mar 2025",
    checkLabel: "Apr 2025–2026",
    dir: "r5-nycplayoffs",
  },
  {
    id: "dc",
    event: "Federal government shutdown",
    measure: "Weekday bike-share activity at DC federal-office stations",
    fit: -15.1,
    check: -19.7,
    fitLabel: "2018–19 shutdown",
    checkLabel: "2025 shutdown",
    dir: "r8-dcshutdown",
  },
  {
    id: "bike",
    event: "Rain day (Central Park)",
    measure: "Citi Bike trips",
    fit: -20,
    check: -20,
    fitLabel: "2023–24",
    checkLabel: "2025",
    approx: true,
    dir: "r2-citibike",
  },
  {
    id: "subway",
    event: "Rain day (Central Park)",
    measure: "NYC subway riders (bus −4%)",
    fit: -3.0,
    check: -2.3,
    fitLabel: "2022–23",
    checkLabel: "2024–25",
    dir: "r2-mta",
  },
  {
    id: "bars",
    event: "Rain day (Central Park)",
    measure: "Visits to NYC bars (drinking places)",
    fit: -2.1,
    check: -3.2,
    fitLabel: "train",
    checkLabel: "holdout",
    dir: "r2-places",
  },
];

export type Declined = { title: string; body: string; dir: string };
export const DECLINED: Declined[] = [
  {
    title: "Game results never matter",
    body: "MSG’s own foot traffic jumps on game nights (+2.4k visits for a Knicks game), but a win vs a loss is null for both teams in every specification. Across 358 venues near MSG, 36 “hits” on wins against 35.8 expected by chance, and none survive correction. Outcomes didn’t move power load (0 of 20) or subway ridership (0 of 10) either.",
    dir: "arena",
  },
  {
    title: "The Knicks-win hedge idea was wrong",
    body: "Our first bet was that the bar across from MSG gains when the Knicks win. It came out −$2,026 a game with a range crossing zero, and −$752 [−$1,936, +$431] with nine more months of data. The real exposure is how many home playoff games you get, not who wins them.",
    dir: "history",
  },
  {
    title: "Single-year weather effects often don’t replicate",
    body: "Taxi rain looked like +$2,212 a day in the fit year. Add month dummies and it falls to +$128; refit on the next year and it’s +$303. Yellow-cab rain flips sign between periods. Passing size, interval and support gates is necessary, not sufficient — so the desk now declines effects that don’t hold up in recent months (“unstable”).",
    dir: "hedgesim",
  },
  {
    title: "Daily weather hedges move little variance",
    body: "Even where rain is real (transit −2–4%), a perfect rain hedge removes about 1–2% of daily variance, because weekday, season and noise dominate. Texas heat is real every year, and its hedge still trims only 4–6% of the monthly swing. We say so on the card instead of overselling.",
    dir: "r2-taxi",
  },
];
