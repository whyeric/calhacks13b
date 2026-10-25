"""Kalshi playoff markets: catalogue, focus-team prices, and hedge backtests on 2025-2026 seasons.

    cd experiments/bar/r5-markets && ../../../backend/.venv/bin/python analyze.py > output.txt

Writes catalogue.csv, focus_prices.csv, series_quotes.csv, series_hedge.csv, season_hedge.csv.
Revenue is in home games (U = 1); multiply by the per-game uplift for dollars.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import data as D
import hedge as h
from fetch_markets import TARGETS

OUT = Path(__file__).parent
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_rows", 300)
rng = np.random.default_rng(0)


# ---------------------------------------------------------------- 1. catalogue


def ticker_pattern(m: dict) -> str:
    ev = m["event_ticker"]
    s, code = ev.split("-", 1)
    code = re.sub(r"^\d\d", "{YY}", code)
    code = re.sub(r"^\{YY\}[A-Z]{3}\d\d", "{YY}{MON}{DD}", code)
    code = re.sub(r"\{YY\}[A-Z]{4,8}(R1|R2|ECF|WCF|FIN|WC|ALDS|NLDS|ALCS|NLCS|WS)?$", r"{YY}{AWAY}{HOME}\1", code)
    code = re.sub(r"\{YY\}[A-Z]{2,4}$", "{YY}{TEAM}", code)
    suf = m["ticker"].rsplit("-", 1)[1]
    suf = "{TEAM}" if re.fullmatch(r"[A-Z]{2,4}", suf) else ("{TEAM}{W}{L}" if re.fullmatch(r"[A-Z]+\d+", suf) else "{N}")
    return f"{s}-{code}-{suf}"


def catalogue() -> pd.DataFrame:
    C = D.candles()
    rows = []
    for league, sers in TARGETS.items():
        for s in sers:
            blob = D.markets()[s]
            ms = blob["markets"]
            if not ms:
                rows.append(dict(league=league, series=s, title=blob["series"].get("title"), markets=0))
                continue
            info = blob["series"]
            by_ev = defaultdict(list)
            for m in ms:
                by_ev[m["event_ticker"]].append(m)
            seasons = sorted({e.split("-", 1)[1][:2] for e in by_ev})
            vols = [float(m.get("volume_fp") or 0) for m in ms]
            ev_vol = [sum(float(m.get("volume_fp") or 0) for m in v) for v in by_ev.values()]
            peak_oi = [max((float(c.get("open_interest") or 0) for c in C.get(m["ticker"], [])), default=np.nan)
                       for m in ms if m["ticker"] in C]
            opens = sorted(min(m["open_time"] for m in v)[:10] for v in by_ev.values())
            rows.append(dict(
                league=league, series=s, title=info.get("title"), pattern=ticker_pattern(ms[0]),
                rule=ms[0]["rules_primary"], sources="; ".join(x["name"] for x in info.get("settlement_sources", [])),
                terms=info.get("contract_terms_url"), seasons=",".join(seasons), events=len(by_ev), markets=len(ms),
                volume_total=sum(vols), volume_median_event=float(np.median(ev_vol)),
                peak_oi_median_market=float(np.nanmedian(peak_oi)) if peak_oi else np.nan,
                first_open=opens[0], last_open=opens[-1],
            ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 2. focus teams


FOCUS = {  # (league, Kalshi code): series to report
    ("nba", "NYK"): ["KXNBAPLAYOFF", "KXNBAEAST", "KXNBA"],
    ("nba", "GSW"): ["KXNBAPLAYOFF", "KXNBAWEST", "KXNBA"],
    ("nhl", "NYR"): ["KXNHLPLAYOFF", "KXNHLEAST", "KXNHL"],
    ("mlb", "SF"): ["KXMLBPLAYOFFS", "KXMLBNL", "KXMLB"],
    ("nfl", "NYG"): ["KXNFLPLAYOFF", "KXNFLNFCCHAMP", "KXSB"],
    ("nfl", "SF"): ["KXNFLPLAYOFF", "KXNFLNFCCHAMP", "KXSB"],
}


def focus_prices(st: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (lg, team), sers in FOCUS.items():
        for s in sers:
            for m in D.markets()[s]["markets"]:
                if m["ticker"].rsplit("-", 1)[1] != team:
                    continue
                cs = D.candles().get(m["ticker"]) or []
                if not cs:
                    continue
                yy = int(m["event_ticker"].split("-", 1)[1][:2]) + 2000
                dates = {"first": cs[0]["end_period_ts"] + 1, "last": cs[-1]["end_period_ts"] + 1}
                if lg in ("nba", "nhl"):
                    dates |= {"Jan 1": D.eve(f"{yy}-01-01").timestamp(), "Mar 1": D.eve(f"{yy}-03-01").timestamp()}
                sub = st[(st.league == lg) & (st.season == yy)]
                if len(sub):
                    dates["playoff eve"] = D.eve(sub.game1.min()).timestamp()
                for r in sub[(sub.a == team) | (sub.b == team)].itertuples():
                    dates[f"{r.round} eve"] = D.eve(r.game1).timestamp()
                close_ts = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")).timestamp()
                for label, ts in dates.items():
                    if label not in ("first", "last") and ts > close_ts + 86400:
                        continue  # market already settled
                    q = D.quote(m["ticker"], datetime.fromtimestamp(ts, D.ET))
                    if q:
                        rows.append(dict(team=team, league=lg, ticker=m["ticker"], when=label, date=q["date"].date(),
                                         mid=round(q["mid"], 3), bid=q["bid"], ask=q["ask"], oi=q["oi"],
                                         vol_cum=round(q["vol_cum"]), result=m["result"]))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3. per-series quotes


def score_key(suffix: str, fmt: str) -> tuple[str, tuple[int, int]] | None:
    mt = re.fullmatch(r"([A-Z]+)(\d+)", suffix)
    if not mt:
        return None
    team, dig = mt.groups()
    need = h.wins_needed(fmt)
    if len(dig) == 2:
        return team, (int(dig[0]), int(dig[1]))
    return team, (need, int(dig) - need)  # FINALSEXACT 'OKC7' = wins 4-3


def series_quotes(st: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in st[st.complete].itertuples():
        cut = D.eve(r.game1)
        q = {}
        for team in (r.a, r.b):
            m = None
            for s in D.WINNER_SERIES[r.league][r.round]:
                if s in ("KXNBASERIES", "KXNHLSERIES", "KXMLBSERIES"):
                    ev = D.pair_event(s, r.season, r.a, r.b)
                    m = next((x for x in ev if x["ticker"].rsplit("-", 1)[1] == team), None)
                else:
                    m = D.team_market([s], r.season, team)
                if m and D.quote(m["ticker"], cut):
                    break
                m = None
            q[team] = (m, D.quote(m["ticker"], cut) if m else None)
        (ma, qa), (mb, qb) = q[r.a], q[r.b]
        if not qa and not qb:
            rows.append(dict(**r._asdict(), priced=False))
            continue
        if qa and qb:
            p_a = qa["mid"] / (qa["mid"] + qb["mid"])
            over = qa["ask"] + qb["ask"] - 1
        else:
            p_a = qa["mid"] if qa else 1 - qb["mid"]
            over = np.nan
        games, scores = {}, {}
        for m in D.pair_event(D.GAMES_SERIES[r.league], r.season, r.a, r.b):
            qq = D.quote(m["ticker"], cut)
            if qq:
                games[int(m["ticker"].rsplit("-", 1)[1])] = qq
        for s in D.SCORE_SERIES[r.league]:
            ms = D.pair_event(s, r.season, r.a, r.b)
            if not ms:  # FINALSEXACT events are named by season only
                ms = [m for m in D.markets()[s]["markets"] if m["event_ticker"].split("-", 1)[1] == D.season_code(r.season)
                      and (score_key(m["ticker"].rsplit("-", 1)[1], r.fmt) or ("",))[0] in (r.a, r.b)]
            for m in ms:
                k = score_key(m["ticker"].rsplit("-", 1)[1], r.fmt)
                qq = D.quote(m["ticker"], cut)
                if k and qq:
                    team, (w, l) = k
                    scores[(w, l) if team == r.a else (l, w)] = qq  # from A's side
            if scores:
                break
        rows.append(dict(
            **r._asdict(), priced=True, p_a=p_a, overround=over,
            a_mkt=ma["ticker"] if ma else None, b_mkt=mb["ticker"] if mb else None,
            a_quote=qa, b_quote=qb, games_q=games, scores_q=scores,
            a_spread=(qa["ask"] - qa["bid"]) if qa else np.nan,
        ))
    return pd.DataFrame(rows)


def side_contracts(row, us_is_a: bool, which: str) -> list[h.Contract]:
    """Round-0 contracts from our side. which: 'W', 'G', 'S' or combos."""
    out = []
    if "W" in which:
        if us_is_a and row.a_quote:
            out.append(h.Contract("win", h.advance(0), row.a_quote["ask"], row.a_quote["bid"]))
        elif not us_is_a and row.b_quote:
            out.append(h.Contract("win", h.advance(0), row.b_quote["ask"], row.b_quote["bid"]))
        else:  # buy the other side's NO <=> our YES
            oq = row.b_quote if us_is_a else row.a_quote
            out.append(h.Contract("win", h.advance(0), 1 - oq["bid"], 1 - oq["ask"]))
    if "G" in which:
        for g, qq in sorted(row.games_q.items()):
            out.append(h.Contract(f"{g}+", h.games_at_least(0, g), qq["ask"], qq["bid"]))
    if "S" in which and row.scores_q:
        keys = sorted(row.scores_q)
        for (wa, wb) in keys[:-1]:  # drop one: the ladder sums to 1
            us, them = (wa, wb) if us_is_a else (wb, wa)
            qq = row.scores_q[(wa, wb)]
            out.append(h.Contract(f"{us}-{them}", h.exact_score(0, us, them), qq["ask"], qq["bid"]))
    return out


def actual_leg(row, us_is_a: bool) -> h.Leg:
    us, them = (row.a_wins, row.b_wins) if us_is_a else (row.b_wins, row.a_wins)
    need = h.wins_needed(row.fmt)
    return h.Leg(True, us_is_a, us, them, us == need, row.a_home if us_is_a else row.b_home)


def series_paths(row, us_is_a: bool, use_scores: bool) -> list[h.Path]:
    p_us = row.p_a if us_is_a else 1 - row.p_a
    if use_scores and row.scores_q and len(row.scores_q) == 2 * h.wins_needed(row.fmt):
        probs = {((wa, wb) if us_is_a else (wb, wa)): qq["mid"] for (wa, wb), qq in row.scores_q.items()}
        return h.paths_from_scores(row.fmt, us_is_a, probs)
    return h.season_paths([h.Round(row.fmt, p_us, 1.0 if us_is_a else 0.0, D.EDGE[row.league])])


def series_hedges(sq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in sq[sq.priced].itertuples():
        for us_is_a in (True, False):
            paths = series_paths(row, us_is_a, use_scores=True)
            ev = sum(p.prob * p.home_games for p in paths)
            actual = h.Path(1.0, [actual_leg(row, us_is_a)])
            base = dict(league=row.league, season=row.season, round=row.round, team=row.a if us_is_a else row.b,
                        home_court=us_is_a, E_home=ev, home=actual.home_games, scores_priced=bool(row.scores_q),
                        games_priced=bool(row.games_q))
            for which in ("W", "G", "WG", "S"):
                cs = side_contracts(row, us_is_a, which)
                if ("G" in which and not row.games_q) or ("S" in which and not row.scores_q) or not cs:
                    continue
                res = h.min_variance_hedge(paths, cs)
                rows.append(dict(**base, strat=which, sd_before=res.sd_before, sd_after=res.sd_after,
                                 exp_cost=res.cost, premium=res.premium, fees=res.fees,
                                 pnl=h.hedge_pnl(res, cs, actual), n=np.round(res.n, 3).tolist()))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 4. season level


def futures_quote(lg: str, season: int, team: str, cut: datetime) -> tuple[float | None, float | None]:
    conf, champ = D.FUTURES[lg]
    out = []
    for sl in (conf, [champ]):
        m = D.team_market(sl, season, team)
        q = D.quote(m["ticker"], cut) if m else None
        out.append(q["mid"] if q else None)
    return tuple(out)


def remaining_rounds(lg: str, team: str, season: int, start_round: str, cut: datetime, first_p: float | None,
                     first_home: float, first_fmt: str) -> list[h.Round]:
    """Rounds from start_round to the final, using the current futures for the rest."""
    names = D.ROUNDS[lg]
    k0 = names.index(start_round)
    p_conf, p_champ = futures_quote(lg, season, team, cut)
    ladder_names = names[k0:]
    n = len(ladder_names)
    # Cumulative P(win through round j), known at: start round (series price), conf champ (j = n-2), title (n-1).
    known = {}
    if first_p is not None:
        known[0] = first_p
    if p_conf is not None and n >= 2:
        known[n - 2] = p_conf
    if p_champ is not None:
        known[n - 1] = p_champ
    if n - 1 not in known:
        return []
    # Fill gaps geometrically (equal conditional win prob across the missing rounds).
    cum, last_k, last_v = [], -1, 1.0
    ks = sorted(known)
    for j in range(n):
        if j in known:
            cum.append(known[j])
            last_k, last_v = j, known[j]
            continue
        nk = next(k for k in ks if k > j)
        steps = nk - last_k
        ratio = (known[nk] / last_v) ** (1 / steps) if last_v > 0 else 0
        cum.append(last_v * ratio ** (j - last_k))
    cum = list(np.minimum.accumulate(np.clip(cum, 1e-4, 1 - 1e-4)))
    fmts = [first_fmt] + [D.fmt_of(lg, r) for r in ladder_names[1:]]
    p_home = [first_home] + [0.5] * (n - 1)
    return h.rounds_from_futures(cum, fmts, p_home, D.EDGE[lg])


def season_hedges(st: pd.DataFrame, sq: pd.DataFrame) -> pd.DataFrame:
    sqi = sq.set_index(["league", "season", "a", "b"]) if len(sq) else sq
    rows = []
    for (lg, yr), sub in st.groupby(["league", "season"]):
        if not sub.complete.all():
            # 2026 MLB: World Series still being played; drop its two teams.
            sub = sub[sub.complete]
            live = st[(st.league == lg) & (st.season == yr) & ~st.complete]
            skip = set(live.a) | set(live.b)
        else:
            skip = set()
        teams = (set(sub.a) | set(sub.b)) - skip
        pre_cut = D.eve(sub.game1.min())
        for team in sorted(teams):
            mine = sub[(sub.a == team) | (sub.b == team)].sort_values("game1")
            total = int(sum(r.a_home if r.a == team else r.b_home for r in mine.itertuples()))
            first = mine.iloc[0]
            us_a = first.a == team
            # Pre-playoff: first-round series price if already listed, else futures only.
            fq = sqi.loc[(lg, yr, first.a, first.b)] if (lg, yr, first.a, first.b) in sqi.index else None
            p_first = None
            if fq is not None and fq.priced:
                p_first = fq.p_a if us_a else 1 - fq.p_a
            rounds = remaining_rounds(lg, team, yr, first["round"], pre_cut, p_first, 1.0 if us_a else 0.0, first.fmt)
            if not rounds:
                continue
            paths = h.season_paths(rounds)
            e_pre = sum(p.prob * p.home_games for p in paths)
            sd_pre = np.sqrt(sum(p.prob * (p.home_games - e_pre) ** 2 for p in paths))
            # Actual path, as legs aligned with `rounds`.
            legs = [actual_leg(r, r.a == team) for r in mine.itertuples()]
            legs += [h.Leg(False)] * (len(rounds) - len(legs))
            actual = h.Path(1.0, legs)
            # Static: buy the pre-playoff ladder (conference champ, champion) and hold.
            static = []
            conf, champ = D.FUTURES[lg]
            n = len(rounds)
            for sl, k in ((conf, n - 2), ([champ], n - 1)):
                m = D.team_market(sl, yr, team)
                qq = D.quote(m["ticker"], pre_cut) if m else None
                if qq and k >= 0:
                    static.append(h.Contract(m["ticker"], h.advance(k), qq["ask"], qq["bid"]))
            if p_first is not None and fq is not None:
                static = side_contracts(fq, us_a, "W") + static
            res_s = h.min_variance_hedge(paths, static) if static else None
            pnl_s = h.hedge_pnl(res_s, static, actual) if static else 0.0
            # Rolling: at each round's eve, hedge that round with its own contracts.
            pnl_roll = {"W": 0.0, "WG": 0.0, "WS": 0.0}
            exp_cost_roll = {"W": 0.0, "WG": 0.0, "WS": 0.0}
            for r in mine.itertuples():
                key = (lg, yr, r.a, r.b)
                if key not in sqi.index or not sqi.loc[key].priced:
                    continue
                row = sqi.loc[key]
                row_t = pd.Series({**row.to_dict(), "fmt": r.fmt, "league": lg})
                ua = r.a == team
                p_us = row.p_a if ua else 1 - row.p_a
                rr = remaining_rounds(lg, team, yr, r.round, D.eve(r.game1), p_us, 1.0 if ua else 0.0, r.fmt)
                if not rr:
                    continue
                pp = h.season_paths(rr)
                k = D.ROUNDS[lg].index(r.round) - D.ROUNDS[lg].index(first["round"])
                act = h.Path(1.0, legs[k:])
                for which in pnl_roll:
                    rt = _Row(row_t)
                    cs = side_contracts(rt, ua, which.replace("S", "S" if row.scores_q else "").replace(
                        "G", "G" if row.games_q else ""))
                    res = h.min_variance_hedge(pp, cs)
                    pnl_roll[which] += h.hedge_pnl(res, cs, act)
                    exp_cost_roll[which] += res.cost
            rows.append(dict(
                league=lg, season=yr, team=team, rounds_played=len(mine), home=total, E_pre=e_pre, sd_model=sd_pre,
                static_pnl=pnl_s, static_cost=res_s.cost if res_s else np.nan,
                static_sd_after=res_s.sd_after if res_s else np.nan,
                roll_W_pnl=pnl_roll["W"], roll_WG_pnl=pnl_roll["WG"], roll_WS_pnl=pnl_roll["WS"],
                roll_W_cost=exp_cost_roll["W"], roll_WG_cost=exp_cost_roll["WG"], roll_WS_cost=exp_cost_roll["WS"],
            ))
    return pd.DataFrame(rows)


class _Row:
    """Attribute access over a Series (side_contracts expects itertuples rows)."""

    def __init__(self, s: pd.Series):
        self.__dict__.update(s.to_dict())


def boot_ratio(a: np.ndarray, b: np.ndarray, reps: int = 4000) -> tuple[float, float, float]:
    """SD(b)/SD(a) with a bootstrap 90% CI (paired resampling)."""
    n = len(a)
    r = np.std(b, ddof=1) / np.std(a, ddof=1)
    idx = rng.integers(0, n, (reps, n))
    rs = np.std(b[idx], axis=1, ddof=1) / np.std(a[idx], axis=1, ddof=1)
    return r, *np.quantile(rs, [0.05, 0.95])


def main() -> None:
    cat = catalogue()
    cat.to_csv(OUT / "catalogue.csv", index=False)
    print("=== CATALOGUE ===")
    print(cat[["league", "series", "pattern", "seasons", "events", "markets", "volume_total", "volume_median_event",
               "peak_oi_median_market", "first_open"]].to_string(index=False))

    st = D.series_table()
    print(f"\n=== SERIES (ESPN) === {len(st)} series, {st.complete.sum()} complete")

    fp = focus_prices(st)
    fp.to_csv(OUT / "focus_prices.csv", index=False)
    print("\n=== FOCUS TEAM PRICES ===")
    print(fp.to_string(index=False))

    sq = series_quotes(st)
    keep = ["league", "season", "round", "a", "b", "a_wins", "b_wins", "winner", "p_a", "overround", "a_spread"]
    sq_out = sq[[c for c in keep if c in sq] + ["priced"]].copy()
    sq_out["games_priced"] = sq.games_q.apply(lambda x: len(x) if isinstance(x, dict) else 0)
    sq_out["scores_priced"] = sq.scores_q.apply(lambda x: len(x) if isinstance(x, dict) else 0)
    sq_out.to_csv(OUT / "series_quotes.csv", index=False)
    pr = sq[sq.priced].copy()
    pr["y"] = (pr.winner == pr.a).astype(float)
    print(f"\n=== PRE-SERIES WINNER PRICES === priced {len(pr)}/{len(sq)} series")
    print(f"Brier market {np.mean((pr.p_a - pr.y) ** 2):.3f}  vs coin-flip 0.250; favourite won "
          f"{np.mean((pr.p_a > .5) == (pr.y == 1)):.0%}; mean |p-.5| {np.mean(abs(pr.p_a - .5)):.2f}")
    print(f"Overround (askA+askB-1) median {np.nanmedian(pr.overround):.3f}, mean {np.nanmean(pr.overround):.3f}; "
          f"YES spread median {np.nanmedian(pr.a_spread):.3f}")
    print("unpriced:", sq[~sq.priced].apply(lambda r: f"{r.league}{r.season} {r['round']} {r.a}-{r.b}", axis=1).tolist())
    sp = defaultdict(list)
    for row in pr.itertuples():
        for qq in row.games_q.values():
            sp[f"{row.league} games"].append(qq["ask"] - qq["bid"])
        for qq in row.scores_q.values():
            sp[f"{row.league} score"].append(qq["ask"] - qq["bid"])
        if row.a_quote:
            sp[f"{row.league} winner"].append(row.a_spread)
    print("median bid-ask spread at series eve:", {k: round(float(np.median(v)), 3) for k, v in sp.items()})
    print(sq_out[sq_out.priced].groupby(["league", "season"])[["games_priced", "scores_priced"]]
          .agg(lambda x: (x > 0).sum()).to_string())

    # Length markets vs the independent-games model and vs outcomes.
    lens = []
    for row in pr.itertuples():
        if not row.games_q:
            continue
        model = h.season_paths([h.Round(row.fmt, row.p_a, 1.0, D.EDGE[row.league])])
        for g, qq in row.games_q.items():
            pm = sum(p.prob for p in model if p.legs[0].us + p.legs[0].them >= g)
            lens.append(dict(league=row.league, g=g, market=qq["mid"], model=pm, spread=qq["ask"] - qq["bid"],
                             hit=float(row.games >= g)))
    lens = pd.DataFrame(lens)
    if len(lens):
        print("\n=== SERIES-LENGTH MARKETS: market vs model vs realised ===")
        print(lens.groupby(["league", "g"]).agg(n=("hit", "size"), market=("market", "mean"), model=("model", "mean"),
                                                 realised=("hit", "mean"), spread=("spread", "median")).round(3)
              .to_string())

    sh = series_hedges(sq)
    sh.to_csv(OUT / "series_hedge.csv", index=False)
    print("\n=== IN-SERIES HOME GAMES: hedge backtest (one row per team-series; U = 1 home game) ===")
    for strat, g in sh.groupby("strat"):
        surprise = (g.home - g.E_home).to_numpy()
        hedged = surprise + g.pnl.to_numpy()
        hedged_c = hedged - hedged.mean()
        r, lo, hi = boot_ratio(surprise, hedged_c) if len(g) > 5 else (np.nan,) * 3
        print(f"{strat:3s} n={len(g):3d}  model var removed {1 - (g.sd_after ** 2).sum() / (g.sd_before ** 2).sum():6.1%}"
              f"  realised SD {np.std(surprise, ddof=1):.3f} -> {np.std(hedged_c, ddof=1):.3f} "
              f"(ratio {r:.2f}, 90% CI {lo:.2f}-{hi:.2f})  exp cost/series {g.exp_cost.mean():.3f}"
              f"  realised cost/series {-g.pnl.mean():.3f}  premium {g.premium.mean():.2f}")
    # Same-sample comparison where all ladders were priced.
    both = sh[sh.games_priced & sh.scores_priced]
    if len(both):
        print("  same sample (games+scores priced):")
        for strat, g in both.groupby("strat"):
            surprise = (g.home - g.E_home).to_numpy()
            hedged = surprise + g.pnl.to_numpy()
            print(f"  {strat:3s} n={len(g)}  realised SD {np.std(surprise, ddof=1):.3f} -> "
                  f"{np.std(hedged - hedged.mean(), ddof=1):.3f}  exp cost {g.exp_cost.mean():.3f} realised cost "
                  f"{-g.pnl.mean():.3f}")

    ss = season_hedges(st, sq)
    ss.to_csv(OUT / "season_hedge.csv", index=False)
    print(f"\n=== SEASON PLAYOFF HOME GAMES (team-seasons n={len(ss)}) ===")
    print(ss.groupby(["league", "season"]).agg(n=("team", "size"), home=("home", "mean"), E_pre=("E_pre", "mean"),
                                                sd_model=("sd_model", "mean")).round(2).to_string())
    surprise = (ss.home - ss.E_pre).to_numpy()
    print(f"bias mean(home - E_pre) {surprise.mean():+.2f}; corr(home, E_pre) {np.corrcoef(ss.home, ss.E_pre)[0, 1]:.2f};"
          f" realised SD of surprise {surprise.std(ddof=1):.2f} vs model SD {np.sqrt((ss.sd_model ** 2).mean()):.2f}")
    for label, pcol, ccol in (("static ladder", "static_pnl", "static_cost"), ("rolling W", "roll_W_pnl", "roll_W_cost"),
                              ("rolling W+G", "roll_WG_pnl", "roll_WG_cost"), ("rolling W+S", "roll_WS_pnl", "roll_WS_cost")):
        hedged = surprise + ss[pcol].to_numpy()
        r, lo, hi = boot_ratio(surprise - surprise.mean(), hedged - hedged.mean())
        p5u, p5h = np.quantile(surprise, .05), np.quantile(hedged, .05)
        print(f"{label:14s} SD {surprise.std(ddof=1):.2f} -> {hedged.std(ddof=1):.2f} (ratio {r:.2f}, 90% CI {lo:.2f}-{hi:.2f});"
              f" var removed {1 - r ** 2:5.1%}; 5th pct {p5u:+.2f} -> {p5h:+.2f}; exp cost {ss[ccol].mean():.3f}"
              f" realised cost {-ss[pcol].mean():.3f} home games/season")
    for team in ("NYK", "GSW"):
        print(ss[ss.team == team].round(3).to_string(index=False))

    # Make-playoffs contracts at the regular-season opener: calibration and spread.
    print("\n=== MAKE-PLAYOFFS PRICES AT SEASON OPENER (2025-26 / 2026 seasons) ===")
    openers = {"KXNBAPLAYOFF-26": "2025-10-21", "KXNHLPLAYOFF-26": "2025-10-07", "KXMLBPLAYOFFS-26": "2026-03-26",
               "KXNFLPLAYOFF-26": "2025-09-04"}
    for ev, day in openers.items():
        s_ = ev.split("-")[0]
        rows_ = []
        for m in D.markets()[s_]["markets"]:
            if m["event_ticker"] != ev or m["result"] not in ("yes", "no"):
                continue
            q = D.quote(m["ticker"], D.eve(day))
            if q:
                rows_.append((m["ticker"].rsplit("-", 1)[1], q["mid"], q["ask"] - q["bid"], m["result"] == "yes",
                              float(m["volume_fp"])))
        df = pd.DataFrame(rows_, columns=["team", "p", "spread", "made", "vol"])
        if len(df):
            print(f"  {ev}: n={len(df)} Brier {np.mean((df.p - df.made) ** 2):.3f} (base-rate "
                  f"{np.mean((df.made.mean() - df.made) ** 2):.3f}); median spread {df.spread.median():.2f}; "
                  f"median volume/team {df.vol.median():,.0f}; sum of mids {df.p.sum():.1f} vs slots {df.made.sum()}")
            foc = df[df.team.isin(["NYK", "GSW", "NYR", "SF", "NYG"])]
            if len(foc):
                print("    focus:", foc.round(3).to_dict("records"))

    # Direct home-game contract: KXMLBPLAYOFFHOST ("hosts at least N playoff games"), 2026 only.
    print("\n=== KXMLBPLAYOFFHOST (2026): price at playoff eve vs realised home games ===")
    mlb26 = st[(st.league == "mlb") & (st.season == 2026)]
    cut = D.eve(mlb26.game1.min())
    for m in sorted(D.markets()["KXMLBPLAYOFFHOST"]["markets"], key=lambda m: (m["event_ticker"], int(m["ticker"].rsplit("-", 1)[1]))):
        team = m["event_ticker"].split("-", 1)[1][2:]
        q = D.quote(m["ticker"], cut)
        got = int(sum(r.a_home if r.a == team else r.b_home for r in mlb26.itertuples() if team in (r.a, r.b)))
        done = all(r.complete for r in mlb26.itertuples() if team in (r.a, r.b))
        print(f"  {m['ticker']:28s} eve mid {q['mid'] if q else float('nan'):.3f} spread "
              f"{(q['ask'] - q['bid']) if q else float('nan'):.2f} vol {float(m['volume_fp']):>8,.0f} result {m['result'] or '-':3s}"
              f" home so far {got}{'' if done else ' (WS live)'}")

    # Model-world check: the same hedges on simulated seasons (removes small-n noise).
    print("\n=== MODEL WORLD: expected variance removed by contract set, a typical 4-round NBA run ===")
    for p1, label in ((0.75, "favourite"), (0.5, "even"), (0.3, "underdog")):
        rounds = [h.Round("2-2-1-1-1", p1, 1.0 if p1 >= .5 else 0.0, 0.28), h.Round("2-2-1-1-1", .5, .5, .28),
                  h.Round("2-2-1-1-1", .45, .5, .28), h.Round("2-2-1-1-1", .45, .5, .28)]
        paths = h.season_paths(rounds)
        sets = {
            "R1 winner": [h.Contract("w", h.advance(0), 0, 0)],
            "ladder (all 4 advance)": [h.Contract(f"w{k}", h.advance(k), 0, 0) for k in range(4)],
            "R1 games ladder": [h.Contract(f"g{g}", h.games_at_least(0, g), 0, 0) for g in (5, 6, 7)],
            "R1 winner+games": [h.Contract("w", h.advance(0), 0, 0)]
            + [h.Contract(f"g{g}", h.games_at_least(0, g), 0, 0) for g in (5, 6, 7)],
            "all rounds winner+games": [h.Contract(f"w{k}", h.advance(k), 0, 0) for k in range(4)]
            + [h.Contract(f"g{k}{g}", h.games_at_least(k, g), 0, 0) for k in range(4) for g in (5, 6, 7)],
            "MLB-style 'hosts >= N'": [h.Contract(f"h{n}", lambda p, n=n: float(p.home_games >= n), 0, 0)
                                        for n in range(3, 17)],
        }
        dist = h.season_home_games_distribution(rounds)
        e = sum(k * v for k, v in dist.items())
        print(f"{label} (R1 p={p1}): E[home]={e:.2f}, P(0 extra beyond R1)={1 - p1:.2f}")
        for name, cs in sets.items():
            res = h.min_variance_hedge(paths, cs)
            print(f"   {name:26s} SD {res.sd_before:.2f} -> {res.sd_after:.2f}  ({res.variance_removed:5.1%} removed)")


if __name__ == "__main__":
    main()
