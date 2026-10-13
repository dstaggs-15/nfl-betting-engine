from nfl_engine.normalize import Identity
from nfl_engine.providers import Context, Kalshi, Underdog


def context(game):
    return Context(
        [game], Identity([{"player_id": "player1", "player_name": "Trevor Lawrence", "team": "JAX"}])
    )


def test_kalshi_exact_live_schema(game, now):
    raw = {
        "markets": [
            {
                "ticker": "KXNFLPASSYDS-26OCT18HOUJAC-JACTLAWRENCE16-250",
                "event_ticker": "KXNFLPASSYDS-26OCT18HOUJAC",
                "status": "active",
                "strike_type": "greater",
                "title": "Trevor Lawrence: 250+ passing yards",
                "floor_strike": 249.5,
                "yes_ask_dollars": "0.5000",
                "no_ask_dollars": "0.5200",
            }
        ]
    }
    lines = Kalshi().normalize(raw, context(game), now)
    assert len(lines) == 2
    assert lines[0].player_id == "player1"
    assert lines[0].threshold == 249.5
    assert lines[0].price == 0.5
    assert lines[1].direction == "under"
    raw["markets"][0]["title"] = "Trevor Laurence: 250+ passing yards"
    assert not Kalshi().normalize(raw, context(game), now)
    raw["markets"][0]["title"] = "Trevor Lawrence: 250+ passing yards"
    raw["markets"][0]["floor_strike"] = 250
    assert not Kalshi().normalize(raw, context(game), now)


def test_underdog_supported_export(game, now):
    ctx = context(game)
    ctx.bindings = {"underdog:line1": {"event_id": game.event_id, "player_id": "player1"}}
    raw = {
        "players": [{"id": 1, "full_name": "Trevor Lawrence", "sport_id": "NFL"}],
        "appearances": [{"id": 2, "player_id": 1, "team_id": 3}],
        "teams": [{"id": 3, "abbr": "JAX"}],
        "over_under_lines": [
            {
                "id": "line1",
                "status": "active",
                "stat_value": "249.5",
                "over_under": {"appearance_stat": {"appearance_id": 2, "display_stat": "Passing Yards"}},
                "options": [{"choice": "higher"}, {"choice": "lower"}],
            }
        ],
    }
    lines = Underdog().normalize(raw, ctx, now)
    assert len(lines) == 2
    assert lines[0].price is None
    assert lines[0].event_id == game.event_id
    raw["over_under_lines"][0]["status"] = "suspended"
    assert not Underdog().normalize(raw, ctx, now)


def test_kalshi_does_not_guess_unknown_market(game, now):
    assert not Kalshi().normalize(
        {"markets": [{"ticker": "other", "status": "active", "title": "Something NFL"}]}, context(game), now
    )


def test_export_cannot_fabricate_freshness(tmp_path, now):
    import json

    import pytest

    from nfl_engine.providers import read_export

    path = tmp_path / "export.json"
    path.write_text(json.dumps({"markets": []}))
    with pytest.raises(ValueError):
        read_export(path)
    path.write_text(json.dumps({"markets": [], "exported_at": "2026-10-12T10:00:00Z"}))
    assert read_export(path)["exported_at"] == "2026-10-12T10:00:00Z"
