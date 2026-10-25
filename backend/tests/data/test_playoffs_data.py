"""ESPN team-schedule parsing for playoff flags (app/data/playoffs.py)."""

import httpx

from app.data import playoffs


def event(date, home_id, away_id, venue, winner_home, completed=True, note=""):
    return {
        "date": date,
        "competitions": [{
            "status": {"type": {"completed": completed}},
            "venue": {"fullName": venue},
            "notes": [{"headline": note}] if note else [],
            "competitors": [
                {"homeAway": "home", "winner": winner_home, "team": {"id": home_id, "abbreviation": "H"}},
                {"homeAway": "away", "winner": not winner_home, "team": {"id": away_id, "abbreviation": "A"}},
            ],
        }],
    }


PAYLOAD = {"events": [
    event("2025-04-20T23:00Z", "18", "8", "Madison Square Garden", True, note="East 1st Round - Game 1"),
    event("2025-04-23T23:30Z", "8", "18", "Little Caesars Arena", True, note="East 1st Round - Game 3"),
    event("2025-04-26T23:00Z", "18", "8", "Madison Square Garden", None, completed=False),
]}


def test_parse_marks_msg_playoff_home_games_with_round_and_ny_date():
    rows = playoffs.parse_schedule(PAYLOAD, "knicks", 2025, playoff=True)
    assert [(r["date"], r["home"], r["round"], r["won"]) for r in rows] == [
        ("2025-04-20", True, "East 1st Round", True),
        ("2025-04-23", False, "East 1st Round", False),  # 23:30Z is 19:30 in New York
    ]


def test_fetch_writes_fixture_through_a_mock_transport(tmp_path):
    def handler(request):
        season_type = request.url.params["seasontype"]
        team = request.url.path.split("/")[-2]
        if team == "18" and season_type == "3":
            return httpx.Response(200, json=PAYLOAD)
        return httpx.Response(200, json={"events": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        df = playoffs.fetch((2025,), fixtures_dir=tmp_path, client=c)
    assert len(df) == 2
    back = playoffs.read_games(tmp_path)
    assert back["playoff"].all() and back["home"].tolist() == [True, False]
