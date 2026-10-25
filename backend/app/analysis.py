"""Analyze one business: features -> `fit_exposures` -> `run_model_check`, cached in the db.

Used by `POST /businesses/{id}/analyze` and by desk runs (which read the cache first).
The cache row is keyed (business, strike) (G11); nothing else is written.
"""

from typing import Any

from app import clock, db
from app.models import AnalyzeResponse


class AnalysisUnavailable(Exception):
    """The business's feature table can't be built (e.g. no restaurant data yet)."""


def cache_key(strike: float | None) -> str:
    return "default" if strike is None else f"strike={strike:g}"


def compute(business_id: str, strike: float | None = None) -> AnalyzeResponse:
    # Heavy imports (pandas, statsmodels) stay out of app start-up.
    from app.data import features
    from app.stats.exposure import fit_exposures
    from app.stats.modelcheck import run_model_check

    strikes: dict[str, float] | None = {"hot": strike} if strike is not None else None
    try:
        df = features.build(business_id)
    except (FileNotFoundError, ValueError) as e:
        raise AnalysisUnavailable(str(e)) from e
    thresholds = db.get_business_thresholds(business_id)
    result = fit_exposures(df, strikes, business_id=business_id, thresholds=thresholds)
    check = run_model_check(df, event="rain", strikes=strikes)
    exposures, dropped = list(result.exposures), list(result.dropped)
    playoff = playoff_exposure(business_id, df, thresholds)
    if playoff is not None:
        (exposures if playoff.hedgeable else dropped).append(playoff)
    # r2_holdout is None when the table has no holdout rows; the response carries null then.
    return AnalyzeResponse(exposures=exposures, dropped=dropped, model_check=check, r2_holdout=result.r2_holdout)


# Businesses next to MSG get the playoff home-game exposure (a pooled near-MSG estimate, I6).
PLAYOFF_BUSINESSES = {"restaurant"}


def playoff_exposure(business_id: str, df, thresholds):
    """`playoff_home` for a business across from MSG, or None (other businesses, missing fixtures).

    The expected number of home games comes from the season futures in the offline Kalshi cache;
    a desk run refreshes that cache online and re-sizes from live prices.
    """
    if business_id not in PLAYOFF_BUSINESSES:
        return None
    from app.data.playoffs import read_games
    from app.markets import season
    from app.stats import playoffs

    try:
        quotes = season.cached_quotes()
        expected = season.expected_home_games(quotes) if quotes else None
    except ValueError:
        expected = None
    try:
        return playoffs.measure(df, business_id=business_id, games=read_games(), expected_count=expected,
                                thresholds=thresholds)
    except FileNotFoundError:
        return None


def analyze(business_id: str, strike: float | None = None) -> AnalyzeResponse:
    """Compute and cache (always recomputes; the analyze route is the explicit refresh)."""
    res = compute(business_id, strike)
    db.put_analysis(business_id, cache_key(strike), res, clock.now().isoformat())
    return res


def cached_or_compute(business_id: str, strike: float | None = None) -> AnalyzeResponse:
    raw: Any = db.get_analysis(business_id, cache_key(strike))
    if raw is not None:
        return AnalyzeResponse.model_validate(raw)
    return analyze(business_id, strike)
