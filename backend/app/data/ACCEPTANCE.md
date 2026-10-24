# C1 · Data layer

> Cross-chunk conflicts are resolved in [CONTRACTS.md](../../../docs/CONTRACTS.md); that file wins over this one.

| | |
|---|---|
| **Scope** | Build the daily revenue series (taxi real, restaurant estimated), shared event data (weather, ESPN schedule, MSG event nights, holidays), and the per-business feature table. Produce the checked-in fixtures. Answer confirm-checks C2–C6. |
| **Files** | `backend/app/data/{taxi,dewey,weather,sports,features}.py`; outputs `fixtures/{taxi_daily,restaurant_daily,msg_visits_daily}.parquet`, `fixtures/schedule_{knicks,rangers}.csv`, weather cache in `fixtures/` |
| **Spec sections** | §2, §3 (C2–C6), §4.1–4.4, §1 I6, §15 |
| **Owner role** | Data |
| **Depends on** | C2 Stats and C4 Agent are consumers (not dependencies). C1 itself needs only `config.py` (owned with C6: zone ID, `AVG_CHECK_USD`, holidays, thresholds, paths). C3 supplies the rain threshold and strike from the matched contract (passed in as args; defaults apply otherwise). C8 owns Makefile `make seed` that calls C1 builders and offline behavior. |
| **Gate** | 3:30 PM: C2–C6 answered, example feature-table rows checked in. 6:00 PM: both daily series and feature tables built. 2:00 AM: weather and schedules cached (never fetched live in demo). |

Naming clash: repo-root `data/` = raw gitignored exports (two Dewey folders, 143 weekly `.snappy.parquet` each, 2024-01-01 onward). `backend/app/data/` = code. Config path constants must keep them distinct.

## Interfaces

**Produces (consumed by C2 Stats, C3 Markets sizing `p̂`, C4 Agent, C6 API, C7 UI labels):**

| Artifact | Shape |
|---|---|
| `taxi_daily.parquet` | `date` (date, local NY), `revenue` float USD (sum `fare_amount`), `trips` int. One row per calendar day, no gaps in the window. |
| `restaurant_daily.parquet` | `date`, `visits` int, `revenue_est` float (= visits × `AVG_CHECK_USD`), `estimated` bool (always true), `place_id` str (opaque; no business name). Aggregated only, no raw rows. |
| `msg_visits_daily.parquet` | `date`, `visits` int, `spike` bool (event-night flag from threshold rule). |
| `schedule_{team}.csv` | `date` (YYYY-MM-DD), `home` bool, `opponent` str, `home_win` bool or empty if not final. Teams: knicks, rangers. |
| Feature table (`features.build(business_id) -> DataFrame`) | `date` date; `revenue` float; `dow` int 0–6 (Mon=0); `doy` int 1–366; `is_holiday` bool; `msg_event` bool; `home_game` bool; `home_win` bool (False when no game); `rain` bool; `rain_open_hours` bool; `tmax` float °F; `estimated` bool. Plus `split` in {`train`,`holdout`} (first 365 days train). One row per day, sorted, unique `date`. |
| Weather | `precipitation_sum` inches, `temperature_2m_max` °F, hourly precipitation; MSG 40.7505, -73.9934, tz America/New_York. Settlement-station weather exposed as a second series with same columns. |

**Function contract (names proposed, C2/C3 must agree):** `features.build(business_id, rain_threshold=0.01, hours=(open,close)) -> DataFrame`; `features.split(df)`; `features.event_frequency(df, col) -> float` (p̂ on `train`, used by C3 `fair`).

**Consumes:** raw TLC Parquet (outside repo), raw Dewey Parquet in `data/`, Open-Meteo archive API, ESPN scoreboard API (`basketball/nba`, `hockey/nhl`), `config.py`.

**Invariants touching this chunk:** I6 (every estimated series carries `estimated=true`; API/UI label comes from this flag). I2 indirectly (all numbers in later text trace to these tables). No raw Dewey rows or business names in git (C6 license).

## Automated acceptance tests

All tests run offline against checked-in fixtures or tiny synthetic inputs under `backend/tests/data/fixtures/`. Network calls mocked.

| ID | Test name | Future test file | Setup / fixture | Assertion |
|---|---|---|---|---|
| C1-A1 | taxi_aggregates_by_local_date | backend/tests/data/test_taxi.py | Synthetic 12-row TLC parquet: 2 zones, pickups at 23:30 and 00:30 local, UTC-stored edge | Only target `PULocationID` kept; trip at 23:30 local counts to that local date; `revenue`=sum fares exactly (tol 1e-9); `trips`=count |
| C1-A2 | taxi_drops_bad_rows | test_taxi.py | Rows with `fare_amount` 0, -3.5, and `trip_distance` 0 | All three excluded; valid row kept; trips count reflects drop |
| C1-A3 | taxi_fills_missing_days | test_taxi.py | Input missing one day | Output has that date with revenue 0 and trips 0 OR is flagged per open question G3; no silent gap; row count = days in window |
| C1-A4 | taxi_cache_roundtrip | test_taxi.py | Build then reload fixture | Columns/dtypes exactly as Interfaces; `date` unique, monotonic; no NaN in `revenue` |
| C1-A5 | taxi_fixture_sanity | test_taxi.py | Checked-in `taxi_daily.parquet` | Covers full chosen window; all `revenue` > 0; median daily revenue within configured plausible band (set after C2/C5, e.g. 5k–60k); no day > 5× median without being listed |
| C1-A6 | dewey_explodes_week_to_7_days | backend/tests/data/test_dewey.py | One synthetic weekly row, `visits_by_day`=[1..7], week_start 2024-01-01 | 7 rows; dates 2024-01-01..07; visits 1..7 in order; sum equals weekly total |
| C1-A7 | dewey_filters | test_dewey.py | Rows with ZIP 10001 and 90210; NAICS 722511 and 445110; week_start 2023-12-25 | Only ZIP in (10001,10119,MSG ZIP) AND NAICS in (722511,722513,722410) AND week_start >= 2024-01-01 survive; ticker `NBA-A` route returns MSG rows |
| C1-A8 | dewey_revenue_est_and_flag | test_dewey.py | visits=[100,...], `AVG_CHECK_USD`=35 | `revenue_est` = visits×35 exactly; `estimated` true on every row; changing env `AVG_CHECK_USD` changes output linearly |
| C1-A9 | dewey_malformed_week | test_dewey.py | `visits_by_day` len 6, null, or JSON string | Raises clear error or skips with logged count; never produces misaligned dates |
| C1-A10 | dewey_no_pii_in_fixture | test_dewey.py | Checked-in restaurant and msg fixtures | Columns exactly as Interfaces (no name, address, lat/long, placekey); row count = days |
| C1-A11 | msg_event_spike_rule | test_dewey.py / test_features.py | Synthetic MSG visits with 3 clear spikes | `spike` true on exactly those days; threshold documented in config (default: > rolling 28-day median + 2×MAD, see G5) |
| C1-A12 | weather_parse_and_units | backend/tests/data/test_weather.py | Recorded Open-Meteo JSON (daily+hourly) | Inches and °F values unchanged; `rain` = precip_sum ≥ 0.01 true/false at 0.0099/0.01; threshold overridable |
| C1-A13 | rain_open_hours_flag | test_weather.py | Hourly: 0.04 in open hours total vs 0.05 vs rain only 06:00 | 0.04 → False; 0.05 → True (≥); rain outside open hours → False, `rain` still True |
| C1-A14 | weather_cache_no_live_fetch | test_weather.py | Cache present; HTTP client patched to raise | Load succeeds without network; with cache absent and offline, raises explicit error naming the missing file |
| C1-A15 | settlement_station_series | test_weather.py | Station coords param | Request uses station lat/long not MSG; output same schema |
| C1-A16 | sports_parse_scoreboard | backend/tests/data/test_sports.py | Recorded ESPN JSON: Knicks home win, home loss, away game, postponed, no game | `home_game` true only for home; `home_win` true only if home and winner; postponed/non-final yields home_game False, no crash; Rangers uses NHL (OT/shootout win counts as win) |
| C1-A17 | sports_timezone_dates | test_sports.py | Game at 00:30 UTC next day | Assigned to NY local date of tip-off |
| C1-A18 | sports_fallback_csv | test_sports.py | ESPN client raises/timeouts | Falls back to `schedule_{team}.csv`; same output schema; fallback flagged in return metadata |
| C1-A19 | sports_cache | test_sports.py | Second call same date | No second HTTP call (one per date, cached) |
| C1-A20 | feature_table_schema | backend/tests/data/test_features.py | Both businesses' fixtures | Columns/dtypes exactly per §4.4 (+`split`); unique sorted dates; no NaN in any column; same date range for events and revenue |
| C1-A21 | feature_derivations | test_features.py | Known dates | `dow`: 2024-01-01 = 0; `doy`: 2024-12-31 = 366; holidays flagged only on config list |
| C1-A22 | home_win_only_on_game_days | test_features.py | Full table | `home_win` ⇒ `home_game` for all rows; `home_game` ⇒ `msg_event` (game day counts as event) |
| C1-A23 | split_boundary | test_features.py | Full table | `train` = first 365 consecutive days exactly; `holdout` strictly after; no overlap, no gap |
| C1-A24 | estimated_flag_by_business | test_features.py | Both tables | taxi `estimated` all False; restaurant all True (I6) |
| C1-A25 | no_leakage_of_future | test_features.py | Build with end date truncated | Earlier rows byte-identical to full build (no look-ahead in spike rule); p̂ computed on `train` only |
| C1-A26 | event_frequency_phat | test_features.py | Synthetic `rain` col, 100 train days, 27 True | `event_frequency` = 0.27; ignores holdout |
| C1-A27 | thresholds_from_config | test_features.py | Override rain threshold and strike via args | `rain` and `hot` columns/inputs change accordingly; defaults 0.01 / 0.05 |
| C1-A28 | offline_build_end_to_end | test_features.py | `DEMO_OFFLINE=1`, network disabled, fixtures present | `build("taxi")` and `build("restaurant")` succeed from fixtures alone, <2 s |
| C1-A29 | determinism | test_features.py | Build twice | DataFrames equal (assert_frame_equal) |
| C1-A30 | rain_sign_sanity | test_features.py | Real fixtures | Mean taxi revenue on `rain` days vs dry days (same dow) within a loose bounded ratio (0.7–1.5), guards against date misalignment |

## Human review checklist

| ID | What to examine | How | Pass looks like |
|---|---|---|---|
| C1-H1 | C2: taxi zone ID | Open `taxi_zone_lookup.csv`; read the configured ID in `config.py` | Zone "Penn Station/Madison Sq West" (or documented neighbor); ID recorded with the source URL |
| C1-H2 | Taxi daily series | `notebooks/01_taxi.ipynb`: line chart of `revenue`, by-dow box plot | Weekly seasonality, holiday dips, no flatlines/zeros, no 10× spikes; 2020-style outages absent |
| C1-H3 | Taxi vs MSG events | Overlay Knicks/Rangers home nights and MSG spikes on taxi chart | Visible but modest lift on event evenings; plausible, not suspicious |
| C1-H4 | Taxi vs MTA cross-check (optional) | Plot Penn Station ridership vs taxi revenue | Positive correlation; if skipped, noted |
| C1-H5 | C3: chosen restaurant | `notebooks/02_restaurant.ipynb`: ranked table of candidates (anonymized ids), chosen venue's daily visits | Busy (hundreds of visits/week), clear rise on MSG event nights, near-continuous 2024+ history; reason written in notebook |
| C1-H6 | MSG spikes | Plot `msg_visits_daily` with spike flags | Spikes align with known games/concerts (spot-check 5 dates against Knicks schedule); count of spike days plausible (roughly 100–180/yr) |
| C1-H7 | C4: avg check | Menu source link in config comment | Value defensible; `AVG_CHECK_USD` documented as assumed; shows "estimated" label downstream |
| C1-H8 | C5: date window | Print min/max date of every source table side by side | Dewey ends ~2026-09-21; TLC latest month noted; Kalshi history (from C3) noted; common window written in `config.py`; train/holdout dates match fallback or the new window is justified |
| C1-H9 | C6: Dewey license | Read Yale/Dewey terms; record quote + link in README note/notebook | Public charts of aggregates allowed, OR fallback applied (aggregates only, raw never committed) |
| C1-H10 | Privacy / git hygiene | `git ls-files \| grep -Ei 'parquet\|\.env'`; `git check-ignore data/` | Only the three aggregate fixtures tracked; `data/` and raw TLC ignored; no venue name/address in any tracked file |
| C1-H11 | Weather sanity | Plot `tmax` and precip for 1 year; compare 3 known dates (e.g. a known NYC storm day) to NWS records | Seasonal curve; rain-day share roughly 30–35%; known storm shows heavy precip |
| C1-H12 | Rain-flag agreement | Report share of `rain` days where `rain_open_hours` also true | Meaningful gap (some days differ) so rule 4 has material to work with; number recorded for C3 |
| C1-H13 | Schedules | Open `schedule_knicks.csv`, `schedule_rangers.csv` | Roughly 41 home games per season each; demo week rows present; results match ESPN for 3 spot checks |
| C1-H14 | Holiday list | Read `config.py` list | Major US holidays covering window; dates correct |
| C1-H15 | Label of estimates | Inspect any restaurant output/chart | "Estimated" wording visible (I6); never shown as real dollars |
| C1-H16 | Story fit | Rough effect eyeballing (rain vs dry means by business) | Taxi rain direction positive and restaurant negative, matching §14 step 5; if not, tell team before 6 PM |

## Fixtures & sample data needed

| Fixture | Used by | Notes |
|---|---|---|
| `fixtures/taxi_daily.parquet` | C2, C6, C7 | Real; tracked in git |
| `fixtures/restaurant_daily.parquet` | C2, C6, C7 | Aggregated, anonymized; tracked |
| `fixtures/msg_visits_daily.parquet` | features, notebook | Tracked |
| `fixtures/weather_msg.parquet` (+ hourly) and `weather_station.parquet` | features, C3 | Cached at import; required for offline |
| `fixtures/schedule_knicks.csv`, `schedule_rangers.csv` | sports fallback | Full window plus demo week |
| `fixtures/features_{taxi,restaurant}.parquet` (optional) | C2 shortcut | Prebuilt feature tables so C2 can start before rebuilds |
| `fixtures/businesses/*.json` example feature rows (5 rows each) | C4, C7 | Needed by 3:30 PM gate |
| Test fixtures `backend/tests/data/fixtures/` | tests | Tiny synthetic TLC parquet, Dewey weekly parquet, recorded Open-Meteo and ESPN JSON |

## Definition of done

- [ ] C2–C6 answered in writing with sources (config comments or notebook).
- [ ] Three parquet fixtures, weather cache, and two schedule CSVs generated by `make seed` and tracked (aggregates only).
- [ ] `features.build` works for both businesses fully offline; schema matches Interfaces.
- [ ] Tests C1-A1..A30 pass; no network in test suite.
- [ ] Human checklist C1-H1..H16 signed off by Data owner; H8, H9, H16 shared with team.
- [ ] No raw data or venue identifiers tracked in git.
- [ ] Notebooks 01 and 02 run top to bottom.

## Spec gaps / open questions

| # | Gap | Proposed default |
|---|---|---|
| G1 | Dewey export is already in repo-root `data/` (two folders, 143 files); spec says export with filters. Which folder is which (Advan vs. second product) and the filtering/duckdb tooling is unclear since python lacks duckdb/pyarrow. | Inspect schema in a venv with pyarrow/duckdb added to backend deps (not the system python); read both folders, document which is which in `dewey.py` docstring. |
| G2 | Business hours for `rain_open_hours` are not specified. | `config.py`: 11:00–23:00 local, adjustable; same for taxi? Taxi runs 24h; use 11:00–23:00 for both, flagged in config. |
| G3 | Missing days (TLC gaps, Dewey weeks absent) not addressed. | Reindex to full calendar; interpolate nothing; mark missing as NaN and drop from train; fail the build if >2% missing. |
| G4 | Daily `msg_event` rule: "visits spike or game day" is unspecified. | `msg_event = home_game OR spike`; spike = visits > rolling median(28d) + 2×MAD, reported counts in notebook. |
| G5 | Dewey `visits_by_day` week alignment (Monday start vs Sunday) and timezone of Advan day. | Assume `week_start` = day index 0 as given; verify with known MSG game dates in H6. |
| G6 | `home_win` false vs null on non-game days; regression needs bool. | False on non-game days (per schema bool); `home_game` is the support gate. |
| G7 | Spec window: TLC availability to date (today 2026-10-24) and Dewey ends 2026-09-21; train "first year" vs C5 fallback (Oct 2024–Sep 2025). | Common window start = max of sources; train = first 365 days of that window; holdout rest; record in `config.py`. |
| G8 | Which postal codes: "MSG's own ZIP if different" unspecified; 10001 and 10119 may both cover it. | MSG ZIP 10121; include it in the list. |
| G9 | Taxi `fare_amount` excludes tips/tolls; "revenue" definition. | Keep `fare_amount` per spec; note in UI as "metered fares". |
| G10 | Two timezones: TLC timestamps are local, Open-Meteo `America/New_York`, ESPN UTC. | All dates local NY; tested in C1-A1, A17. |
| G11 | Holidays list contents not given. | US federal holidays plus Christmas Eve and New Year's Eve. |
| G12 | Settlement station weather (NOAA vs Open-Meteo) owned by whom: C1 or C3. | C1 provides station-parameterized loader; C3 passes coordinates; Open-Meteo default. |
