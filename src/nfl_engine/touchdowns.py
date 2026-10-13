"""Shared touchdown arrival process and mutually exclusive scorer allocation."""

import numpy as np

from .model import prior_rows
from .schemas import Market


class Touchdowns:
    def __init__(self, history, cutoff, rng, count, games):
        self.history = prior_rows(history, cutoff)
        self.rng, self.count, self.games = rng, count, games
        self.cache = {}

    def team_profile(self, team):
        rows = [r for r in self.history if r["team"] == team and r.get("opportunities_available")]
        ids = sorted(
            {r["event_id"] for r in rows},
            key=lambda event: max(r["kickoff"] for r in rows if r["event_id"] == event),
        )[-12:]
        rows = [r for r in rows if r["event_id"] in ids]
        if len(ids) < 6:
            return None
        td_by_game = {r["event_id"]: r.get("team_tds", 0) for r in rows}
        rate = (sum(td_by_game.values()) + 2.5 * 4) / (len(ids) + 4)
        opportunities = {}
        receiving_opportunities = {}
        rushing_opportunities = {}
        # Weight observed goal-line opportunities rather than averaging player TDs.
        for row in rows:
            if row.get("position") not in ("QB", "RB", "WR", "TE"):
                continue
            pid = row["player_id"]
            receiving_opportunities[pid] = receiving_opportunities.get(pid, 0) + row.get("redzone_targets", 0)
            rushing_opportunities[pid] = rushing_opportunities.get(pid, 0) + row.get("redzone_carries", 0)
            score = row.get("redzone_carries", 0) + row.get("redzone_targets", 0)
            score += 2 * (row.get("goal_line_carries", 0) + row.get("goal_line_targets", 0))
            opportunities[row["player_id"]] = opportunities.get(row["player_id"], 0) + score
        # An explicit other scorer category covers defense/special teams and sparse roles.
        players = sorted(opportunities)
        weights = np.array(
            [opportunities[p] + 0.5 for p in players] + [max(2, sum(opportunities.values()) * 0.1)]
        )
        weights /= weights.sum()
        pass_share = (sum({r["event_id"]: r.get("team_pass_tds", 0) for r in rows}.values()) + 4) / (
            sum(td_by_game.values()) + 8
        )
        qb_attempts = {}
        for r in rows:
            if r.get("position") == "QB":
                qb_attempts[r["player_id"]] = qb_attempts.get(r["player_id"], 0) + (r.get("attempts", 0) or 0)
        qbs = sorted(qb_attempts)
        qb_weights = np.array([qb_attempts[p] for p in qbs], dtype=float)
        if qb_weights.sum():
            qb_weights /= qb_weights.sum()
        pass_chances = np.array(
            [
                (receiving_opportunities[p] + 0.5)
                / (receiving_opportunities[p] + rushing_opportunities[p] + 1)
                for p in players
            ]
            + [pass_share]
        )
        return rate, players, weights, pass_chances, qbs, qb_weights

    def simulate(self, line):
        if line.event_id not in self.cache:
            profiles = {team: self.team_profile(team) for team in [line.team, line.opponent]}
            if any(v is None for v in profiles.values()):
                return None
            pace, _ = self.games[line.event_id]
            results = {}
            first_arrivals = {}
            for team, (rate, players, weights, pass_chances, qbs, qb_weights) in profiles.items():
                intensities = rate * np.exp(0.15 * pace - 0.01125)
                # A Poisson process: exponential waits followed by scorer allocation.
                arrivals = np.cumsum(
                    self.rng.exponential(1 / np.maximum(intensities[:, None], 0.01), size=(self.count, 16)),
                    axis=1,
                )
                valid = arrivals < 1
                allocations = self.rng.choice(len(players) + 1, size=arrivals.shape, p=weights)
                for index, player in enumerate(players):
                    results[(team, player, Market.ANYTIME_TD)] = np.sum(
                        valid & (allocations == index), axis=1
                    )
                passing = valid & (self.rng.random(valid.shape) < pass_chances[allocations])
                if qbs and qb_weights.sum():
                    passers = self.rng.choice(len(qbs), size=arrivals.shape, p=qb_weights)
                    for index, qb in enumerate(qbs):
                        results[(team, qb, Market.PASS_TD)] = np.sum(passing & (passers == index), axis=1)
                first_arrivals[team] = (arrivals[:, 0], allocations[:, 0], players)
            teams = list(profiles)
            for team in teams:
                time, scorers, players = first_arrivals[team]
                other_time = first_arrivals[teams[1] if team == teams[0] else teams[0]][0]
                for index, player in enumerate(players):
                    results[(team, player, Market.FIRST_TD)] = (
                        (time < 1) & (time < other_time) & (scorers == index)
                    ).astype(float)
            self.cache[line.event_id] = results
        return self.cache[line.event_id].get((line.team, line.player_id, line.market))
