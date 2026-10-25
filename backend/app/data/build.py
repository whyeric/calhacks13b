"""`make seed-data`: rebuild every tracked data fixture from raw TLC files and the network.

Writes `fixtures/taxi_daily.parquet`, both weather caches, both schedule CSVs, the prebuilt
`features_{business}.parquet` and `features/{business}_rows.json` (5 example rows each). The restaurant
outputs are skipped with a message until the Dewey build has produced `restaurant_daily.parquet`.
"""

from __future__ import annotations

import json
import logging

from app import config
from app.data import features, sports, taxi, weather

log = logging.getLogger(__name__)


def main() -> None:
    out = config.FIXTURES_DIR
    df = taxi.build()
    print(f"taxi_daily: {len(df)} days, median revenue {df['revenue'].median():,.0f}")

    for lat, lon in (config.MSG_LATLON, config.SETTLEMENT_STATION_LATLON):
        name = weather.series_name(lat, lon)
        for path in weather.cache_paths(name, out):
            path.unlink(missing_ok=True)
        w = weather.load_weather(lat, lon, offline=False)
        print(f"weather_{name}: {len(w.daily)} days")

    print("schedules:", sports.build())

    (out / "features").mkdir(exist_ok=True)
    for business in features.BUSINESSES:
        try:
            table = features.build(business)
        except FileNotFoundError as e:
            print(f"features_{business}: skipped ({e})")
            continue
        table.to_parquet(out / f"features_{business}.parquet", index=False)
        rows = features.example_rows(business)
        (out / "features" / f"{business}_rows.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(f"features_{business}: {len(table)} rows")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
