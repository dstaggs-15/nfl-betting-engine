import re

from .schemas import Market

LABELS = {
    "anytime td": Market.ANYTIME_TD,
    "anytime touchdown": Market.ANYTIME_TD,
    "first td": Market.FIRST_TD,
    "first touchdown": Market.FIRST_TD,
    "receptions": Market.RECEPTIONS,
    "receiving yards": Market.RECEIVING,
    "rushing yards": Market.RUSHING,
    "rush rec yards": Market.SCRIMMAGE,
    "rushing receiving yards": Market.SCRIMMAGE,
    "passing yards": Market.PASSING,
    "passing tds": Market.PASS_TD,
    "passing touchdowns": Market.PASS_TD,
    "rushing attempts": Market.CARRIES,
    "rush attempts": Market.CARRIES,
    "targets": Market.TARGETS,
    "longest reception": Market.LONG_REC,
    "longest rush": Market.LONG_RUSH,
}


def key(name: str):
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def market(label):
    normalized = re.sub(r"\s+", " ", re.sub(r"[+/_-]", " ", label.lower())).strip()
    return LABELS.get(normalized)


class Identity:
    def __init__(self, players, aliases=None):
        self.players = {p["player_id"]: p for p in players}
        self.index = {}
        for p in players:
            self.index.setdefault((key(p["player_name"]), p["team"]), set()).add(p["player_id"])
        self.aliases = aliases or {}

    def match(self, name, team):
        alias = self.aliases.get((name, team))
        if alias is not None:
            player = self.players.get(alias)
            return alias if player and player["team"] == team else None
        matches = self.index.get((key(name), team), set())
        return next(iter(matches)) if len(matches) == 1 else None
