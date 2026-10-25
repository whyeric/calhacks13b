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
    # r2_holdout is None when the table has no holdout rows; the response carries null then.
    return AnalyzeResponse(
        exposures=result.exposures, dropped=result.dropped, model_check=check, r2_holdout=result.r2_holdout
    )


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
