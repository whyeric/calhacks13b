"""Write fixtures/settlement_rates.json: p̂ for each contract's settlement flag on train (R17).

    cd backend && python -m scripts.settlement_rates

Needs the C1 feature table (#20: app.data.features and its tracked weather fixtures). The markets
layer never assumes a rate; the desk passes this p̂ into size_hedge as the fair-value input.

KXRAIN-<date>-NYC resolves YES iff CLINYC (Central Park) total precipitation is "strictly greater
than 0 inches", with trace and missing values counted as 0. The gauge reports hundredths, so the
flag is daily precipitation >= 0.01 in at the Central Park point.
"""

import json
from decimal import ROUND_HALF_UP, Decimal

from app import config
from app.data import features

RAIN_THRESHOLD_IN = 0.01  # from the KXRAIN rules above, not the data-layer default
OUT = config.FIXTURES_DIR / "settlement_rates.json"


def _home_win(train) -> dict:
    # Game markets settle on the result itself, so p̂ is the home win rate over home-game days.
    games = train[train["home_game"]]
    n, wins = len(games), int(games["home_win"].sum())
    return {
        "p_hat": str((Decimal(wins) / Decimal(n)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
        "settlement_col": "home_win", "universe": "home_game days (Knicks + Rangers at MSG)",
        "series": "KXNBAGAME (NYK home), KXNHLGAME (NYR home)",
        "train": [str(train["date"].min()), str(train["date"].max())],
        "n_train_days": n, "n_event_days": wins,
        "source": "home_win / home_game on the taxi feature table (#20)",
    }


def main() -> None:
    df = features.add_settlement(
        features.build("taxi"), *config.SETTLEMENT_STATION_LATLON, rain_threshold=RAIN_THRESHOLD_IN,
    )
    train = df[df["split"] == "train"]
    n_days, n_rain = len(train), int(train["settle_rain"].sum())
    p_hat = (Decimal(n_rain) / Decimal(n_days)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    assert abs(float(p_hat) - features.event_frequency(df, "settle_rain")) < 1e-4
    out = {
        "rain": {
            "p_hat": str(p_hat),
            "settlement_col": "settle_rain",
            "series": "KXRAIN (-NYC markets)",
            "station": "CLINYC, Central Park",
            "latlon": [str(x) for x in config.SETTLEMENT_STATION_LATLON],
            "rule": "daily precipitation >= 0.01 in (contract: > 0 in; trace counts as 0)",
            "train": [str(train["date"].min()), str(train["date"].max())],
            "n_train_days": n_days,
            "n_event_days": n_rain,
            "source": "app.data.features.add_settlement + event_frequency on the taxi feature table (#20)",
        },
        "home_win": _home_win(train),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
