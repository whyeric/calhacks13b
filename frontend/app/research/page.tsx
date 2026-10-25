import type { Metadata } from "next";
import Link from "next/link";
import {
  DECLINED,
  FINDINGS,
  SOURCE_BASE,
  source,
  type Finding,
} from "@/lib/research";
import { barSpan, position } from "@/lib/chartScale";

export const metadata: Metadata = {
  title: "Why this works · Hedge Desk",
  description: "What the Hedge Desk research found, and what it declined",
};

const DOMAIN: [number, number] = [-30, 130];
// Research percentages as printed in RESULTS.md: sign and symbol only.
const signed = (value: number) =>
  `${value > 0 ? "+" : ""}${String(value).replace("-", "−")}%`;

function Bars({ row }: { row: Finding }) {
  const fit = barSpan(row.fit, DOMAIN);
  const check = barSpan(row.check, DOMAIN);
  return (
    <div className="rbar-track">
      <span
        className="rbar-zero"
        style={{ left: `${position("0", DOMAIN)}%` }}
      />
      <span
        className="rbar fit"
        style={{ left: `${fit.x}%`, width: `${fit.width}%` }}
        title={`${row.fitLabel}: ${signed(row.fit)}`}
      />
      <span
        className="rbar check"
        style={{ left: `${check.x}%`, width: `${check.width}%` }}
        title={`${row.checkLabel}: ${signed(row.check)}`}
      />
    </div>
  );
}

export default function Research() {
  return (
    <main className="research">
      <header>
        <div className="brand">
          <span className="brand-icon" aria-hidden="true">
            H
          </span>
          <div>
            <h1>Hedge Desk</h1>
            <p>Why this works</p>
          </div>
        </div>
        <Link href="/" className="research-link">
          ← Back to the desk
        </Link>
      </header>

      <section className="intro research-intro">
        <div>
          <span className="eyebrow">The research behind the desk</span>
          <h2>We tested 40+ hypotheses. A few held up.</h2>
          <p>
            Each effect below was fit on one period, then refit on an
            independent later period, corrected for multiple testing and checked
            against placebos (fake dates, the wrong venue, the off-season). The
            desk only offers protection where all of that held, and declines the
            rest out loud.
          </p>
        </div>
      </section>

      <section className="panel" aria-labelledby="found-heading">
        <div className="section-heading">
          <h2 id="found-heading">What we found</h2>
          <span className="legend-keys" aria-hidden="true">
            <span className="key fit" /> Fit period
            <span className="key check" /> Independent check
          </span>
        </div>
        <p className="muted">
          % change on event days vs comparable days. Both bars must point the
          same way, clear of zero, for us to call it found.
        </p>
        <div className="rchart" aria-hidden="true">
          {FINDINGS.map((row) => (
            <div className="rchart-row" key={row.id}>
              <span className="rchart-label">{row.measure}</span>
              <Bars row={row} />
              <span className="rchart-value">
                {row.approx ? "≈" : ""}
                {signed(row.fit)} / {signed(row.check)}
              </span>
            </div>
          ))}
        </div>
        <table className="research-table">
          <caption>Every finding, with its source</caption>
          <thead>
            <tr>
              <th scope="col">Event → what moved</th>
              <th scope="col">Fit period</th>
              <th scope="col">Independent check</th>
              <th scope="col">Source</th>
            </tr>
          </thead>
          <tbody>
            {FINDINGS.map((row) => (
              <tr key={row.id}>
                <th scope="row" className="text-left">
                  <strong>{row.event}</strong>
                  <br />
                  {row.measure}
                </th>
                <td>
                  {row.approx ? "≈" : ""}
                  {signed(row.fit)} <small>({row.fitLabel})</small>
                </td>
                <td>
                  {row.approx ? "≈" : ""}
                  {signed(row.check)} <small>({row.checkLabel})</small>
                </td>
                <td>
                  <a
                    href={source(row.dir)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {row.dir}
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-labelledby="hedge-heading">
        <h2 id="hedge-heading" className="research-h2">
          …and it can be hedged
        </h2>
        <div className="research-grid">
          <article className="panel">
            <span className="eyebrow">Playoff season</span>
            <h3>Protect the home games you might not get</h3>
            <p>
              Playoff nights bring about 6% more people to the blocks around MSG
              — 2.5× a regular game — and MSG-area driver earnings rise 36–40%.
              Nobody knows in October whether that’s 3 home games or 10.
              Kalshi’s series, conference and title contracts settle exactly on
              advancement, so “NO on the Knicks” pays in the seasons the bar
              loses those nights.
            </p>
            <dl className="research-stats">
              <div>
                <dt>Season swing removed</dt>
                <dd>42–87%</dd>
              </div>
              <div>
                <dt>Cost</dt>
                <dd>≈3% of expected uplift</dd>
              </div>
            </dl>
            <small>
              42–73% SD cut in 20k simulated seasons; 87% of variance removed on
              real 2025–26 prices (84 team-seasons). The realised Knicks runs
              lost money on the hedge because New York kept advancing — that’s
              insurance doing its job.{" "}
              <a href={source("r5-markets")}>r5-markets</a> ·{" "}
              <a href={source("r5-mobility")}>r5-mobility</a> ·{" "}
              <a href={source("r5-nycplayoffs")}>r5-nycplayoffs</a>
            </small>
          </article>
          <article className="panel">
            <span className="eyebrow">DC government shutdown</span>
            <h3>The loss grows with every day, so hedge the duration</h3>
            <p>
              Federal-office districts lost 15% of weekday activity in the
              2018–19 shutdown and 20% in 2025, replicated on separate pre- and
              post-COVID data. A downtown lunch spot lost about $20.2k in 2025.
              One “shutdown happens” contract left it −$16.1k; a ladder of
              “lasts more than N days” contracts left it −$2.9k.
            </p>
            <dl className="research-stats">
              <div>
                <dt>2025 loss, binary hedge</dt>
                <dd>−$16.1k</dd>
              </div>
              <div>
                <dt>2025 loss, duration ladder</dt>
                <dd>−$2.9k</dd>
              </div>
            </dl>
            <small>
              Honest caveats: only 3 shutdowns; buying a binary before every
              deadline since 2021 lost money; a DHS-only lapse in 2026 settled
              the contracts YES with no downtown effect.{" "}
              <a href={source("r8-dcshutdown")}>r8-dcshutdown</a>
            </small>
          </article>
          <article className="panel">
            <span className="eyebrow">Texas heat</span>
            <h3>+$32 a day on the power bill, every year</h3>
            <p>
              A Dallas small business on a fixed-rate plan (~$190/day of power)
              pays about $32 more on days DFW tops 95°F: +$32.2 in 2019–23 and
              +$31.5 in 2024–26, and it shows up in all 8 years. The matching
              Kalshi high-temperature contract pays on exactly that day.
            </p>
            <small>
              The hedge is real but modest: it trims 4–6% of the month’s swing.{" "}
              <a href={source("r4-ercot")}>r4-ercot</a>
            </small>
          </article>
          <article className="panel">
            <span className="eyebrow">Rain</span>
            <h3>Real, replicated, and small</h3>
            <p>
              On Central Park rain days bike share falls about 20%, transit 2–4%
              and bar foot traffic 2–3%, in both the fit and the check years.
              Rain is one slice of a noisy day, so a rain hedge removes only a
              few percent of the swing — and the card says so. Weather is NOAA’s
              Central Park record, the same station Kalshi’s NYC contracts
              settle on (Kalshi has used The Weather Company’s reading there
              since Aug 2026).
            </p>
            <small>
              <a href={source("r2-citibike")}>r2-citibike</a> ·{" "}
              <a href={source("r2-mta")}>r2-mta</a> ·{" "}
              <a href={source("r2-places")}>r2-places</a>
            </small>
          </article>
        </div>
      </section>

      <section aria-labelledby="declined-heading">
        <h2 id="declined-heading" className="research-h2">
          What we declined, and why
        </h2>
        <div className="research-grid">
          {DECLINED.map((row) => (
            <article className="panel declined-card" key={row.title}>
              <h3>{row.title}</h3>
              <p>{row.body}</p>
              <small>
                <a href={source(row.dir)}>{row.dir}</a>
              </small>
            </article>
          ))}
        </div>
      </section>

      <section className="panel research-method" aria-label="Method and limits">
        <h2>How we kept ourselves honest</h2>
        <ul>
          <li>
            40+ hypotheses across 39 experiments, each with a holdout refit, and
            placebos for the ones we call found.
          </li>
          <li>
            Multiple-testing correction (Benjamini–Hochberg) and
            autocorrelation-robust errors (Newey-West) throughout.
          </li>
          <li>
            Bar dollars are <strong>estimates</strong>: visits × an assumed $35
            check and 300 covers a night. Foot traffic and bike trips stand in
            for revenue.
          </li>
          <li>
            Small samples: 15–29 playoff evenings per period, 3 shutdowns, and
            Kalshi sports prices only from 2025.
          </li>
        </ul>
        <small>
          All results: <a href={`${SOURCE_BASE}/SUMMARY.md`}>experiments/bar</a>{" "}
          on the <code>experiments/bar</code> branch.
        </small>
      </section>
      <footer>No real orders are placed. · The owner always decides.</footer>
    </main>
  );
}
