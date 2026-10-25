# R7 tsa: national air travel (Kalshi KXTSAW) → Midtown tourist restaurants and bars

## Mechanism (written before fitting)

Chain: more people fly nationally in a given week (TSA checkpoint screenings) → more out-of-town
visitors in Manhattan that week → more visits to restaurants and bars in the tourist core
(Times Square / Midtown / Hudson Yards / Penn: ZIPs 10036, 10019, 10001, 10018) **relative to**
residential neighborhoods (UES 10021/10028/10075/10128, UWS 10023/10024/10025, West Village 10014).
Kalshi KXTSAW settles on the weekly average of TSA's published daily screenings (Mon–Sun week),
so a Midtown venue worried about a soft tourist week would buy NO on "above X".

Prediction: the elasticity of log(tourist/local) with respect to the weekly TSA surprise is > 0.
The local basket on its own is the placebo (it should show ~0, or at least less than the tourist basket).

Pre-specified design:
- Unit: Mon–Sun week, the same week as KXTSAW. Dewey balanced panel (stores in all weeks, <5% flat weeks), summed per basket.
- Surprise A (trend): log weekly TSA entered alongside year-month FE and holiday controls, so only within-month weekly deviations identify it.
- Surprise B (YoY): log(TSA_w / TSA_{w−52 weeks}), with the same FE and controls (holiday dummies for this year and for the comparison week a year earlier).
- Holiday handling: H1 = control dummies (week contains a federal holiday; Thanksgiving week; the Christmas/New Year weeks; Easter week); H2 = drop every flagged week (and, for YoY, weeks whose comparison week was flagged).
- Outcomes: log(tourist/local) (main), log(tourist), log(local) (placebo).
- Train: weeks ending 2024-01-07..2025-03-30; holdout: weeks ending 2025-04-06..2026-09-27. HAC(4) errors, z = 1.645.
- Extra falsification: permute the surprise within year-month on train (200 draws), and use the *next* week's TSA surprise.

## Data

- **TSA:** daily checkpoint screenings scraped from tsa.gov/travel/passenger-volumes (pages for 2023, 2024 and 2025, plus the current page), 2023-01-01..2026-10-22, 1,391 days. No access block.
- **Kalshi KXTSAW** ("weekly average TSA screenings above X", Mon–Sun week, strike ladder at 0.05M steps): 189 settled markets over 9 weeks (2026-08-23..2026-10-18). The API returns no older history; the legacy series TSAW, TSA and KXTSA are empty. KXTSAD (daily) exists too.
- **Dewey:** balanced panel, 143 weeks (2024-01..2026-09). Tourist basket: 1,728 stores; local basket: 1,882 stores. Weekly visit sums only.

## Settlement basis (step 4)

The weekly Mon–Sun mean of TSA's daily numbers **exactly matches** Kalshi's `expiration_value` for all 8 settled weeks that report one, and it reproduces **189/189** market results. The settlement is fully rebuildable from public data, back to 2023.

## Results (12 pre-registered fits; BH runs across all 12; β = elasticity of weekly visits with respect to TSA)

| outcome | surprise | holidays | train β [90% CI] (n) | holdout β [90% CI] (n) | train BH q | mechanical FOUND |
|---|---|---|---|---|---|---|
| log(tourist/local) | A trend | H1 control | +0.29 [+0.14, +0.43] (65) | +0.40 [+0.26, +0.54] (78) | 0.003 | yes |
| log(tourist/local) | A trend | H2 drop | +0.36 [+0.22, +0.50] (48) | +0.50 [+0.37, +0.62] (59) | 0.0001 | yes |
| log(tourist/local) | B YoY | H1 | −0.02 [−0.38, +0.34] (65) | +0.18 [−0.08, +0.43] (78) | 0.93 | no |
| log(tourist/local) | B YoY | H2 | −0.27 [−0.68, +0.15] (38) | +0.45 [+0.10, +0.81] (54) | 0.50 | no |
| log(tourist) | A trend | H1 | +0.68 [+0.52, +0.85] | +0.75 [+0.58, +0.91] | <0.001 | yes |
| log(tourist) | A trend | H2 | +0.58 [+0.39, +0.77] | +0.72 [+0.46, +0.98] | <0.001 | yes |
| log(tourist) | B YoY | H1 | +0.14 [−0.35, +0.63] | +0.46 [−0.10, +1.01] | 0.76 | no |
| log(tourist) | B YoY | H2 | −0.13 [−0.80, +0.54] | +0.93 [+0.15, +1.70] | 0.82 | no |
| log(local), placebo | A trend | H1 | **+0.40 [+0.24, +0.55]** | **+0.35 [+0.14, +0.56]** | <0.001 | (placebo fails) |
| log(local), placebo | A trend | H2 | +0.22 [+0.03, +0.41] | +0.22 [−0.03, +0.48] | 0.11 | — |
| log(local), placebo | B YoY | H1 | +0.16 [−0.16, +0.49] | +0.28 [−0.17, +0.73] | 0.60 | — |
| log(local), placebo | B YoY | H2 | +0.14 [−0.19, +0.47] | +0.47 [−0.19, +1.14] | 0.66 | — |

Spread of the regressor: surprise A has an SD of about 9% within the sample; surprise B has an SD of about 3%.

### Falsification: what the "trend" effect actually is

- **Seasonality test (decisive):** replace this year's TSA level with **last year's same-week TSA**. That number is known a year in advance, so any contract already prices it in. It predicts the ratio just as well: +0.39 (p<0.001) on train and +0.53 (p<0.001) on holdout, against +0.36 and +0.50 for the actual level. Entered jointly, the YoY surprise adds nothing: −0.12 (p=0.55) on train, +0.08 (p=0.61) on holdout. So surprise A is the calendar. Within a month, the weeks when America flies (spring break, early summer, the run-up to holidays) are also the weeks when Midtown's tourist share is high. That correlation is real and replicates, but it is fully forecastable seasonality, not a TSA *surprise*.
- **Placebo:** the local basket also loads on surprise A with H1 (+0.40, replicated). Part of the A effect is common seasonality across all of Manhattan.
- **Permutation within year-month** (ratio, H2, train): A has real t = +4.17 against a permutation p95 of 2.52 (p = 0.01). B has real t = −1.06 (p = 0.59). The permutation test can't separate seasonality from surprise, because it shuffles within the month.
- **Lead test:** next week's TSA, given this week's, is insignificant (+0.09, p = 0.41 on train; +0.11, p = 0.23 on holdout).

### What a contract would actually pay on

KXTSAW opens on the Monday of its week, so its price already reflects that week's expected level. Proxy strike = last year's same week × the trailing 8-week YoY growth (known before the week). The flag 1[TSA below the proxy strike] correlates −0.68 / −0.71 with the forecast surprise (train / holdout).
- On that flag, log(tourist/local) moves **+0.30% [−0.92, +1.52]** on train and −1.85% [−2.89, −0.81] on holdout. log(tourist) moves −0.25% [−1.68, +1.18] on train and −2.66% [−4.89, −0.43] on holdout. Train is null, so this doesn't qualify. The holdout signal is noted but not acted on (no tuning on holdout). These 6 fits are extra to the 12 above.
- **Hedge backtest** (tourist basket, $35/visit, train β, price = train frequency + $0.02 + fee, 78 holdout weeks): SD of deseasonalised weekly revenue went from 4.753M to 4.739M (**−0.3%**), and the 5th percentile got *worse* (−6.50M → −6.58M). In effect, no hedge.

## Verdict

**NOT FOUND (as a hedge).** The trend specs pass the mechanical FOUND rules (train, holdout and BH, 4 of the 8 non-placebo fits). But the decisive falsification shows that effect is predictable seasonality: last year's TSA explains it just as well. The only hedgeable part, the surprise relative to what's already known (YoY, or a forecast strike), does **not** move the tourist share on train (−0.02 / −0.27). The contract-flag hedge cuts SD by 0.3% and worsens the 5th-percentile week.

Plain reading: Midtown tourist restaurants *do* ride the national travel calendar (elasticity ~0.4 of tourist share to the seasonal TSA level). A seasonal budget handles that; a Kalshi contract can't, because the contract prices the calendar too. The weekly TSA surprise is ~3% SD, and national noise from flights to Orlando or Denver dilutes it before it reaches Manhattan.

Tests run: 12 pre-registered + 6 contract-flag + 2 permutation + 2 seasonal + 2 lead + 6 descriptive. Only the 12 enter BH.

Reproduce: `cd backend && .venv/bin/python ../experiments/bar/r7-tsa/run.py` (TSA pages are cached at r2-cache/r7tsa_*). Output: `results.csv`.
