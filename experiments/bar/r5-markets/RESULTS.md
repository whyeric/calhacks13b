# r5-markets: Kalshi playoff-advancement contracts as the hedge instrument

**Question.** Which Kalshi contracts settle on NBA / NHL / MLB / NFL playoff advancement? How liquid are they and how were they priced? Given a per-home-game uplift U, which contracts, and how many, minimise the variance of a nearby business's playoff revenue, and what does that cost?

**Data.** The public Kalshi API: `/series`, `/markets` plus `/historical/markets` (markets settled before the 2026-08-25 archive cutoff), and daily candlesticks. That covers 50 series, about 4,000 markets and about 2,300 candle histories. ESPN scoreboard gives every 2025–2026 postseason game (82 series; home court and length are checked against the actual host of each game). Caches live in `r2-cache/r5markets_*`.

**Method.** `hedge.py` is a small numpy-only model, and `test_hedge.py` holds its 37 tests. It treats each game as an independent Bernoulli trial with a league home edge, and fits per-game strength to the series price. It enumerates every playoff path (round reached, home court, exact score) and solves the minimum-variance hedge `n* = -Cov(X)^-1 Cov(X, U*H)` over any set of contract payoffs. The backtest uses the real quote at the daily close before game 1 (midnight ET, so there is no look-ahead). Positions are bought at the ask: YES at the ask, NO at 1 − bid. The Kalshi fee 0.07·p·(1−p) is included, and every position is held to the real settlement.

**Caveat up front.** Kalshi sports futures only begin in Jan 2025, so there are two seasons of history (2025 and 2026 playoffs). Series-length and exact-score ladders exist only from the 2026 playoffs (plus the 2025 Finals and MLB 2025 exact-score series).

---

## 1. Catalogue (full table: `catalogue.csv`)

Volume is in contracts ($1 notional each). "Median event" is the median total volume across all markets of one event, e.g. one series or one season's futures. Event codes put the home-court team **second** (`{AWAY}{HOME}`) in 101 of 102 checks; the exception is `KXNHLSERIES-26VGKANAR2`, where VGK had home court. Take home court from the schedule, not the ticker.

| Outcome | NBA | NHL | MLB | NFL | Settles on (source) | Opens | Liquidity (median event) |
|---|---|---|---|---|---|---|---|
| Make playoffs | `KXNBAPLAYOFF-{YY}-{TEAM}` | `KXNHLPLAYOFF-{YY}-{TEAM}` | `KXMLBPLAYOFFS-{YY}-{TEAM}` | `KXNFLPLAYOFF-{YY}-{TEAM}` | "If X qualifies for the playoffs in the {season}" (league site, ESPN). NBA play-in losers = No | Right after the prior season: NBA Jul 10, NHL Aug–Sep, MLB Dec 17, NFL Feb 11 | NBA 0.35M, NHL 0.12M, MLB 3.6M, NFL 4.0M per season (peak OI ~4–9k per team) |
| Series winner, per round | `KXNBASERIES-{YY}{AWAY}{HOME}{R1\|R2}-{TEAM}` | `KXNHLSERIES-…{R1\|R2}-{TEAM}` | `KXMLBSERIES-{YY}{AWAY}{HOME}{WC\|ALDS\|…\|WS}-{TEAM}` (2025 tickers have no round tag) | (single games: `KXNFLGAME`) | "If X wins the X vs Y {round} series" (league, ESPN, Fox). Closes early when decided | **1–6 days before game 1** (median 2), once the matchup is set | NBA **9.7M**, NHL 0.78M, MLB 0.49M per series; peak OI NBA 1.7M, NHL 0.21M; spread 1¢; two-sided overround median 2¢ |
| Conference / league final winner | `KXNBAEAST/WEST-{YY}-{TEAM}` | `KXNHLEAST/WEST-{YY}-{TEAM}` | `KXMLBAL/NL-{YY}-{TEAM}`; 2026 also `KXMLBSERIES-…ALCS/NLCS` | `KXNFLAFCCHAMP/NFCCHAMP-{YY}-{TEAM}` | Wins the conference finals / pennant | Right after the prior Finals (e.g. `KXNBAEAST-27` opened 2026-06-16) | NBA 21–23M, NHL 2M, MLB 10–18M, NFL 46–61M |
| Championship | `KXNBA-{YY}-{TEAM}` | `KXNHL-{YY}-{TEAM}` | `KXMLB-{YY}-{TEAM}` | `KXSB-{YY}-{TEAM}` | Wins the Finals / Cup / WS / Super Bowl | Night of the prior final (`KXNBA-27` opened 2026-06-14) | NBA 130M, NHL 14M, MLB 112M, NFL 197M |
| Reach a round (qualifier) | `KXNBAECFQUAL/WCFQUAL-{YY}-{TEAM}` (new for 2026-27, ~0 volume), `KXTEAMSINNBAEF/WF/F-{YY}-{PAIR}` | `KXTEAMSINSC-{YY}-{PAIR}` | `KXMLBALCSQUAL/NLCSQUAL-{YY}-{TEAM}` (2026, 0.25M) | `KXNFLROUNDQUAL-{YY}{DIV\|CONF}-{TEAM}`, `KXNFLSTAGEOFELIM-{YY}{TEAM}-{WC\|DIV\|CONF\|FL\|FW\|REG}` (2026-27, thin) | Qualifies for the round / exact matchup | Pre-season | Pair markets are thin per pair |
| **Series length** | `KXNBASERIESGAMES-{YY}{AWAY}{HOME}{RND}-{5\|6\|7}` | `KXNHLSERIESGAMES-…-{5\|6\|7}` | `KXMLBSERIESGAMES-…-{3\|4\|5\|6\|7}` | – | "above g−0.5 games are played" (league, ESPN) | With the series (**2026 playoffs on**) | **Thin:** NBA 35k, NHL **2.6k**, MLB 6k per series; spread NBA 3¢, NHL 10¢, MLB 5¢ |
| **Exact series score** | `KXNBASERIESSCORE-…-{TEAM}{W}{L}`; Finals 2025 `KXNBAFINALSEXACT-25-{TEAM}{G}` | `KXNHLSERIESSCORE-…`, `KXNHLFINALSEXACT-25-…` | `KXMLBSERIESSCORE-…` (2026), `KXMLBSERIESEXACT-{YY}{MON}{DD}{PAIR}-{TEAM}{W}{L}` (2025) | – | Final series score (8 outcomes for best-of-7) | With the series | NBA 0.43M, NHL 76k, MLB 24–66k per series; spread 1–3¢ |
| **Home games hosted** | – | – | **`KXMLBPLAYOFFHOST-{YY}{TEAM}-{N}`**: "X hosts at least N playoff games" (2026: NYY, BOS, LAD, CHC, MIL only) | `KXNFLPLAYOFFHOST-{YY}-{TEAM}`: hosts ≥ 1 non-SB playoff game (2026-27, 4.5k total volume) | ESPN / MLB.com | 2 weeks before the MLB playoffs (2026-09-16); NFL preseason | 3–34k per market, spread 1–9¢ |
| Other length-related | `KXNBAGAME7-{YY}-{N}` (number of game 7s **league-wide**), `KXNBASWEEP`, `KXNBAHOMECLINCH` (Finals only), `KXNBAPLAYOFFWINS-{YY}{TEAM}-{N}` (≥N playoff wins, 5 teams, 2026) | – | `KXMLBWSOUTCOME` | – | | | 15k–1.5M |

**There is no NBA/NHL contract that pays per home game for one team.** The closest are the series-length ladder (≥5, ≥6, ≥7 games) and the exact-score ladder. They are equivalent here, because within one series the home games are a deterministic function of the length. With home court in a 2-2-1-1-1 series, H = 2 + 1{≥5} + 1{=7}. Without it, H = 2 + 1{≥6}. MLB's `KXMLBPLAYOFFHOST` is the only contract that settles directly on a team's season count of hosted games. It priced correctly in 2026: every settled threshold matches the realised counts (LAD 4, NYY 3, BOS/CHC 0), and `MIL-9` settled No mid-World-Series once 9 became unreachable. `KXNBAGAME7` is league-wide, so it is no use to one business.

## 2. Focus teams (full table: `focus_prices.csv`)

| Team / season | Make playoffs (opener → eve) | Path and pre-series prices (mid) | Home games |
|---|---|---|---|
| **Knicks 2025** | – (made, ~0 volume) | R1 vs DET p=0.785 (W 4-2) → R2 @BOS **p=0.145** (W 4-2) → ECF vs IND p=0.60 (L 2-4). Title 0.025 on the playoff eve | 9 vs E 6.1 |
| **Knicks 2026** | 0.955 → made | R1 vs ATL 0.72 (4-2), R2 vs PHI 0.705 (4-0), ECF vs CLE 0.705 (4-0), Finals @SAS **0.36 (W 4-1)**. `KXNBA-26-NYK`: 0.13 (Jul) → 0.07 (Jan 1) → 0.035 (playoff eve) → 0.085 → 0.155 → 0.365 → won; 72M contracts traded | 9 vs E 6.6 (two sweeps capped it) |
| **Warriors 2025** | 0.955 on the eve | R1 @HOU 0.61 (W 4-3, 3 home) → R2 @MIN 0.365 (L 1-4, 2 home) | 5 vs E 5.4 |
| **Warriors 2026** | **0.745 at the opener**, 0.625 Mar 1, 0.26 on the eve → missed (play-in) | – | 0 |
| **Rangers 2025 / 2026** | 2026: **0.635 at the opener** → 0.36 Jan 1 → 0.02 Mar 1 → missed. 2025: no volume | – | 0 / 0 |
| **SF Giants 2025 / 2026** | 2026: 0.42 at the opener (10¢ spread) → missed. 2025: 0.01 by the eve | – | 0 / 0 |
| **NY Giants 2025-26** | 0.125 at the opener → missed. `KXNFLPLAYOFF-27-NYG` trades 0.29 now | – | 0 |
| (49ers 2025-26) | 0.65 → made; out in the divisional round | `KXNFLNFCCHAMP-25-SF` | – |

The Rangers and Warriors 2025-26 are the textbook downside case. A business priced ~5.3 extra home games into the season (the average E[H] for a playoff team), and the make-playoffs NO cost 0.26–0.37 at the opener and paid $1.

## 3. How the markets price

- **Winner prices are informative and tight.** Over 79 pre-series quotes the Brier score is 0.207, against 0.25 for a coin flip, and favourites won 72%. The bid-ask spread is 1¢ and the two-sided overround is a median 2¢.
- **Length prices match the independent-games model** fitted to the winner price alone, within 1–2 pp. For example, NBA P(≥6) is 0.487 in the market vs 0.496 in the model, and P(7) is 0.215 vs 0.233. So the length ladder is fairly priced relative to the winner market. The model in `hedge.py` can therefore stand in for missing ladder prices, and neither side is cheap.
- **Make playoffs at the opener**: Brier NBA 0.162 (base rate 0.249), NHL 0.243 (0.250), MLB 0.213, NFL 0.228. The mids sum to the number of slots (16.1 vs 16), so there is no systematic overround. Spreads are 1–3¢ (NHL 7¢).

## 4. Hedge math (`hedge.py`)

```python
import hedge as h
# Expected extra home games: R1 at 0.72 with home court, then the futures ladder.
rounds = h.rounds_from_futures([0.72, 0.32, 0.145, 0.035], ["2-2-1-1-1"] * 4, [1, .5, .5, .5], edge=0.28)
h.season_home_games_distribution(rounds)          # {2: .03, 3: .16, ..., 16: .00}, mean 6.6
h.home_games_distribution("2-2-1-1-1", h.implied_theta(0.72, "2-2-1-1-1", 0.28), True, 0.28)  # one series
# Optimal contracts for U dollars per home game:
paths = h.season_paths(rounds)
cs = h.series_contracts(0, "2-2-1-1-1", win=(0.73, 0.72), games={5: (.93, .90), 6: (.61, .60), 7: (.28, .24)})
res = h.min_variance_hedge(paths, cs, uplift=U)    # res.n (+YES / -NO), res.sd_after, res.cost, res.fees
```

Knicks 2026 R1 eve, per $1 of U: buy **4.8 NO on the R1 series** (exposure to the next three rounds) plus **1 NO on "≥5 games" and 1 NO on "game 7"** (exposure to this round's games 5 and 7). That takes SD from 3.02 to 2.10 home games, for an expected cost of 0.07 home games. The rest is later-round risk, re-hedged at each series. At the Finals eve (no later rounds), the hedge is just **1 NO on "≥6 games"**, which takes SD from 0.49 to 0.

The structural point is that the two contract types hedge different risks. The **series-winner** contract hedges *future* rounds. The **length/score** contract hedges *this* round's home games. Within a series the winner contract removes only 2.5% of the variance in that series's home games.

## 5. Backtest on real settled prices

**(a) One series, target = that series's home games** (n = team-series, prices at the eve of game 1; `series_hedge.csv`):

| Contracts | n | Model variance removed | Realised SD (home games) | Ratio (90% bootstrap CI) | Expected / realised cost per series | Fee share of cost |
|---|---|---|---|---|---|---|
| Winner only | 158 | 2.5% | 0.531 → 0.529 | 1.00 (0.97–1.02) | 0.004 / 0.008 | 45% |
| Length ladder (≥5/≥6/≥7) | 70 | 95.3% | 0.557 → 0.154 | **0.28 (0.18–0.36)** | 0.071 / 0.043 | 24% |
| Exact-score ladder | 82 | 99.6% | 0.569 → 0.106 | **0.19 (0.14–0.23)** | 0.137 / 0.117 | 29% |

The leftover SD for the length/score ladders comes from bid-ask and rounding of the realised book, not from basis: the payoff is a deterministic function of the same outcome.

**(b) Whole playoff run, target = the team's season playoff home games** (84 team-seasons: NBA and NHL 2025 and 2026, MLB 2025 and the settled part of 2026; `season_hedge.csv`). Unhedged surprise vs the pre-playoff market expectation has SD **2.37 home games** (the mean surprise is −0.09, so E[H] is unbiased; corr(H, E_pre) = 0.64).

| Strategy | Hedged SD | Ratio (90% CI) | Variance removed | 5th-percentile surprise | Expected / realised cost per season |
|---|---|---|---|---|---|
| Unhedged | 2.37 | – | – | −3.20 | – |
| Static: buy the pre-playoff ladder once (R1 series + conference + title NO) | 1.12 | 0.47 (0.39–0.57) | 77% | −1.87 | 0.14 / 0.14 |
| Rolling: series-winner NO at each round | 0.86 | 0.36 (0.31–0.43) | 87% | −1.55 | 0.15 / 0.10 |
| Rolling: winner + length ladder | 0.78 | 0.33 (0.28–0.38) | 89% | −1.54 | 0.21 / 0.14 |
| Rolling: winner + exact score | 0.72 | 0.30 (0.25–0.36) | 91% | −1.77 | 0.28 / 0.22 |

In dollars: with an average E[H] ≈ 5.2 home games, the rolling winner hedge costs about **2–3% of expected playoff uplift** (0.10–0.15 home games × U) and removes about **87%** of its variance. For example, at U = $10k per home game, the unhedged SD of about $23.7k becomes about $8.6k for roughly $1–1.5k a season. Adding length contracts takes the variance removed to 89–91% but doubles the cost, because those ladders have wider spreads. Model world (no small-n noise, typical 4-round NBA run): winner contracts on all rounds remove 90–94%, adding length on all rounds removes 98–99%, and an MLB-style "hosts ≥ N" ladder removes 100%.

## Verdict

- **Basis: FOUND, and exact.** Kalshi has settled contracts on every advancement step for all four leagues, with clear rules (league site / ESPN). Their payoffs are deterministic functions of the same outcome that sets the home-game count. Series-winner and futures markets are deep (NBA series ~10M contracts, 1¢ spreads, 2¢ overround) and priced well (Brier 0.207).
- **Hedge effectiveness: FOUND** on real prices and outcomes. Rolling series-winner hedges cut season home-game SD by 64% (90% CI 57–69%), i.e. 87% of variance, at a realised cost of 0.10 home games per season. Length/score ladders cut in-series SD by 72–81%.
- **Per-game contracts:** these exist only as series-length / exact-score ladders (NBA, NHL, MLB, 2026 onward) and MLB `KXMLBPLAYOFFHOST`. Length matches home-game count *exactly* within a series, which a winner contract cannot do. But it is **thin**: NHL length markets trade ~2.6k contracts per series with 10¢ spreads. A business with U = $10k would need ~10k contracts per threshold, more than the whole NHL event volume. Use NBA length/score markets and MLB host markets when size allows, and winner/futures contracts as the deep default.

**Limits.** Only two seasons exist (n = 84 team-seasons, 79 priced series), and only 2026 has length ladders. The model holds the per-game probability fixed and uses a fixed league home edge. Home court in rounds after the next is taken as 0.5 when not yet known. Pre-playoff R2 prices do not exist, so they are filled geometrically between the R1 and conference prices. Quotes are daily closes; the real fill depends on depth (OI above).

Files: `fetch_markets.py`, `fetch_games.py` (cache), `data.py`, `analyze.py` → `output.txt` and the CSVs. `hedge.py` and `test_hedge.py` form the product-ready module (`backend/.venv/bin/python -m pytest experiments/bar/r5-markets/test_hedge.py`).
