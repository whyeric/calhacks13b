"""C1-A16..A19: ESPN scoreboard parsing, NY dates, CSV fallback, per-date cache."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.data import sports

ESPN = Path(__file__).parent / "fixtures" / "espn"
KNICKS, RANGERS = sports.TEAMS["knicks"], sports.TEAMS["rangers"]


def _load(name: str) -> dict:
    return json.loads((ESPN / f"{name}.json").read_text())


def _flags(games: list[sports.Game], day: date):
    return sports.daily_flags(sports.schedule_frame(games), day, day).iloc[0]


@pytest.mark.parametrize(
    "name, day, home_game, home_win",
    [
        ("nba_home_win_20241025", date(2024, 10, 25), True, True),
        ("nba_home_loss_20241028", date(2024, 10, 28), True, False),
        ("nba_away_20241022", date(2024, 10, 22), False, False),
        ("nba_home_postponed_synthetic", date(2025, 1, 9), False, False),
        ("nba_no_game", date(2024, 7, 1), False, False),
    ],
)
def test_sports_parse_scoreboard(name, day, home_game, home_win):  # C1-A16
    games = sports.parse_scoreboard(_load(name), KNICKS)
    row = _flags(games, day)
    assert bool(row["home_game"]) is home_game
    assert bool(row["home_win"]) is home_win


def test_postponed_game_is_dropped():  # C1-A16
    assert sports.parse_scoreboard(_load("nba_home_postponed_synthetic"), KNICKS) == []


def test_rangers_shootout_win_counts():  # C1-A16 (NHL, OT/SO)
    payload = _load("nhl_home_shootout_win_20250118")
    assert payload["events"][0]["status"]["type"]["detail"] == "Final/SO"
    (game,) = sports.parse_scoreboard(payload, RANGERS)
    assert game.home and game.final and game.won
    row = _flags([game], game.date)
    assert row["home_game"] and row["home_win"]


def test_sports_timezone_dates():  # C1-A17
    payload = _load("nba_home_win_late_utc_20241115")
    assert payload["events"][0]["date"].startswith("2024-11-16T00:30")
    (game,) = sports.parse_scoreboard(payload, KNICKS)
    assert game.date == date(2024, 11, 15)


def test_unfinished_game_not_counted():  # C1-A16 non-final
    payload = _load("nba_home_win_20241025")
    payload["events"][0]["status"]["type"].update(completed=False, state="pre", name="STATUS_SCHEDULED")
    (game,) = sports.parse_scoreboard(payload, KNICKS)
    assert not game.final and game.won is None
    row = _flags([game], game.date)
    assert not row["home_game"] and not row["home_win"]


def test_sports_fallback_csv(tmp_path):  # C1-A18
    (tmp_path / "schedule_knicks.csv").write_text(
        "date,home,opponent,home_win\n2024-10-25,True,IND,True\n2024-10-28,True,CLE,False\n2024-10-30,False,MIA,\n"
    )

    def fail(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    client = sports.ScoreboardClient(http=httpx.Client(transport=httpx.MockTransport(fail)))
    df, meta = sports.games("knicks", date(2024, 10, 24), date(2024, 10, 30), client=client, offline=False, fixtures_dir=tmp_path)
    assert meta["source"] == "csv" and meta["fallback"] is True and meta["error"]
    assert list(df.columns) == ["date", "home_game", "home_win"]
    by = df.set_index("date")
    assert by.loc[date(2024, 10, 25)].tolist() == [True, True]
    assert by.loc[date(2024, 10, 28)].tolist() == [True, False]
    assert by.loc[date(2024, 10, 30)].tolist() == [False, False]
    assert len(df) == 7

    online, meta2 = sports.games(
        "knicks", date(2024, 10, 25), date(2024, 10, 25),
        client=_replay_client({"20241025": _load("nba_home_win_20241025")}), offline=False, fixtures_dir=tmp_path,
    )
    assert meta2 == {"source": "espn", "fallback": False, "error": None}
    assert list(online.columns) == list(df.columns)


def _replay_client(by_day: dict[str, dict]) -> sports.ScoreboardClient:
    def handler(request):
        return httpx.Response(200, json=by_day.get(request.url.params["dates"], {"events": []}))

    return sports.ScoreboardClient(http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_sports_cache():  # C1-A19
    client = _replay_client({"20241025": _load("nba_home_win_20241025")})
    first = client.get(KNICKS.league, date(2024, 10, 25))
    second = client.get(KNICKS.league, date(2024, 10, 25))
    assert first is second and client.calls == 1
    client.get(RANGERS.league, date(2024, 10, 25))
    assert client.calls == 2


def test_checked_in_schedules():
    for team in sports.TEAMS:
        df = sports.read_schedule(team)
        assert list(df.columns) == sports.CSV_COLUMNS
        home = df[df["home"]]
        assert 30 <= len(home[home["date"] < "2025-08-01"]) <= 60  # one season of home games plus playoffs
