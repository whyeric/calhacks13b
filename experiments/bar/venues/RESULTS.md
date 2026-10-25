# Venue scan near MSG: is there a "bar that gains on Knicks wins"?

**Question.** Does any eligible Dewey venue near MSG show a real, measurable revenue effect on Knicks/Rangers
home wins (or rain)?

**Method.** I took all 358 eligible candidates from `dewey.rank_candidates`: ZIPs 10001/10119/10121, NAICS
722511/722513/722410, coverage of at least 98% and at least 200 visits a week. For each venue, revenue = visits x $35,
put into the `features.build("restaurant")` table with the same calendar, weather, schedule and split. Each venue is fit
with `fit_exposures(strikes={"hot": 85})` (OLS, HC3, train = 2024-10-01..2025-09-30). Across the 358 venues I applied
Benjamini-Hochberg FDR at 10% and Bonferroni (family alpha 0.10). For stability I refit the same design on train only
and on holdout only.

Script: `venue_scan.py` (run from backend/, takes about 11 s). Per-venue summary numbers, keyed by opaque id only:
`venue_scan_summary.csv`.

## Multiple comparisons (358 venues, 49 home-win days and 148 rain days in train)

| event | raw sig @90% | pos / neg | expected by chance | pass all gates (pos) | BH 10% | Bonferroni |
|---|---|---|---|---|---|---|
| home_win | 36 | 3 / 33 | 35.8 | 34 (3) | **0** | **0** |
| rain | 45 | 23 / 22 | 35.8 | 40 (19) | **0** | **0** |
| hot (>85F, side check) | 75 | 61 / 14 | 35.8 | 74 (60) | 10 | 3 |

Across venues the home_win t-stats have sd 0.95 and the rain t-stats sd 1.06, close to the N(0,1) you would see if
nothing were there. The number of "significant" home_win venues (36) is exactly what chance predicts (35.8), and they
skew negative. Train-vs-holdout correlation of the venue effects: home_win -0.07, rain +0.12. So the train effects
do not carry over into the holdout.

## Top 10 by home_win t-stat (train fit)

| place_id | NAICS | ZIP | visits/wk | home_win $ | CI90 | p | n | gates | BH | R2 holdout | holdout-only $ (p) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| p_aa7923b4d504 | 722513 | 10001 | 332 | +346 | [121, 572] | 0.012 | 49 | yes | no | -0.09 | +56 (0.78) |
| p_32b9eef46b1e | 722511 | 10001 | 925 | +241 | [13, 470] | 0.083 | 49 | yes | no | 0.42 | +405 (0.012) |
| p_c654d8d174e1 | 722410 | 10001 | 3687 | +928 | [4, 1853] | 0.099 | 49 | yes | no | 0.67 | -673 (0.38) |
| p_5fdf254def67 | 722511 | 10001 | 1681 | +1279 | [-84, 2641] | 0.123 | 49 | no | no | -0.07 | +1022 (0.28) |
| p_40010f203031 | 722511 | 10001 | 1363 | +984 | [-70, 2037] | 0.124 | 49 | no | no | -0.69 | +386 (0.24) |
| p_634c015d6ea0 | 722511 | 10001 | 398 | +128 | [-12, 268] | 0.133 | 49 | no | no | 0.44 | -130 (0.17) |
| p_40bf6ed320c1 | 722511 | 10001 | 2452 | +1444 | [-231, 3120] | 0.156 | 49 | no | no | -0.53 | +666 (0.59) |
| p_f891f68490a3 | 722511 | 10001 | 2188 | +1393 | [-256, 3042] | 0.165 | 49 | no | no | -0.80 | -552 (0.41) |
| p_1a1579f24a67 | 722513 | 10001 | 482 | +607 | [-122, 1336] | 0.171 | 49 | no | no | -0.14 | +55 (0.92) |
| p_4f2e605f7ae4 | 722511 | 10001 | 3073 | +1344 | [-323, 3010] | 0.185 | 49 | no | no | -0.05 | +397 (0.73) |

There are 51 home-win days in the holdout. None of these is a bar (722410) that passes both the gates and replication.
The current demo bar `p_afa556030e60` sits at home_win -$2,026 (t -1.43); its holdout-only fit is +$588 (p 0.61).

**Rain:** the strongest |t| venues are p_eb186f3725b0 (-$739, p 0.001), p_4da9687d536d (-$977, p 0.003) and
p_3384c4a5e9a1 (+$386, p 0.004). None survives BH. On holdout the first is -$339 (p 0.18) and the others are
indistinguishable from 0.

## The one lead, and why it is not enough

`p_32b9eef46b1e` (722511 full-service restaurant, not a bar; 10001; about 925 visits/wk) is the only venue whose
home_win effect points the same way in both periods: train +$241 [13, 470], p 0.08; holdout +$405, p 0.012. It also has
a decent fit (R2 0.52 / 0.42). But it fails BH and Bonferroni. With 358 venues, about 0.4 venues would be expected to show
p<0.10 in train and p<0.05 in holdout in the same direction by chance alone (358 x 0.05 x 0.025 ≈ 0.45). So one venue
doing it is what chance predicts. I picked it after the fact, so it is a hypothesis, not a finding.

## Side note: hot (>85F) is not a clean signal either

Hot has 10 BH survivors and 3 Bonferroni survivors, almost all positive. But the train-vs-holdout correlation of hot
effects across venues is **-0.34**, and only 1 of the 3 Bonferroni survivors replicates in holdout (p_ace338e64825,
722513, +$4,313 train and +$3,533 holdout, p 0.0002). The 55 hot train days are all in summer 2025, so they are tied to
the seasonal harmonics and to venue-specific level shifts. I treat it as a lead for the hot/temperature experiment, not
as evidence here.

## Verdict

No. Among 358 eligible venues near MSG, **zero** home_win and **zero** rain effects survive BH 10% or Bonferroni. The
count of raw "significant" venues matches what chance predicts, the t-stats look like a standard normal (sd 0.95), and
the effects do not carry from train to holdout (cross-venue corr -0.07). Picking the top venue by home_win t would be
p-hacking: the #1 venue (+$346, p 0.012) goes to +$56 (p 0.78) on holdout. The one venue that replicates in direction
(`p_32b9eef46b1e`) is a restaurant, not a bar, fails multiple-comparison correction, and one such venue is what chance
predicts. There is no defensible "bar that gains on Knicks wins" in this Dewey data. One plausible reason: daily foot-traffic
panels near Penn Station/MSG are dominated by commuter and transit noise, and game nights already shift the baseline
(handled by the `home_game` / `msg_event` controls), so win-vs-loss adds little.

**Demo-worthy?** Not as a hedgeable bar exposure. It is demo-worthy as an honesty beat: "we scanned 358 venues, applied
FDR, and found nothing, so the desk declines to hedge home wins." That fits the decline rules.
