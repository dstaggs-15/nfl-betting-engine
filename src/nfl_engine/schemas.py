from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def aware(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class Market(StrEnum):
    ANYTIME_TD = "anytime_touchdown"
    FIRST_TD = "first_touchdown"
    RECEPTIONS = "receptions"
    RECEIVING = "receiving_yards"
    RUSHING = "rushing_yards"
    SCRIMMAGE = "rushing_receiving_yards"
    PASSING = "passing_yards"
    PASS_TD = "passing_touchdowns"
    CARRIES = "rushing_attempts"
    TARGETS = "targets"
    LONG_REC = "longest_reception"
    LONG_RUSH = "longest_rush"


class Game(Record):
    event_id: str
    season: int
    week: int
    home: str
    away: str
    kickoff: datetime
    status: Literal["scheduled", "live", "final", "postponed"] = "scheduled"


class Line(Record):
    line_id: str
    provider: Literal["underdog", "prizepicks", "kalshi"]
    provider_market_id: str
    event_id: str
    player_id: str
    player_name: str
    team: str
    opponent: str
    market: Market
    threshold: float = Field(ge=0)
    direction: Literal["over", "under"]
    display_line: str
    price_type: Literal["multiplier", "contract", "unknown"] = "unknown"
    price: float | None = Field(default=None, gt=0)
    collected_at: datetime
    raw_source_hash: str
    available: bool = True
    fee_type: Literal["quadratic", "unknown"] = "unknown"
    fee_multiplier: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def economics(self):
        if self.price_type == "contract" and (self.price is None or self.price >= 1):
            raise ValueError("contract price must be between zero and one")
        if self.price_type == "multiplier" and (self.price is None or self.price <= 1):
            raise ValueError("gross multiplier must exceed one")
        return self


class Prediction(Record):
    prediction_id: str
    line: Line
    probability: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    sample_size: int = Field(ge=0)
    mean: float
    median: float
    recent_hit_rate: float
    historical_hit_rate: float
    opponent_factor: float
    status: Literal["RECOMMENDED", "WATCH", "PASS", "INSUFFICIENT_DATA", "STALE_LINE"]
    reason_codes: list[str] = []
    risk_codes: list[str] = []
    model_version: str


class Ticket(Record):
    ticket_id: str
    provider: str
    legs: list[str]
    event_ids: list[str]
    joint_probability: float = Field(ge=0, le=1)
    naive_probability: float = Field(ge=0, le=1)
    uncertainty: float = Field(ge=0)
    multiplier: float | None = None
    break_even: float | None = None
    expected_profit: float | None = None
    fair_multiplier: float | None = None
    weakest_leg: str
    lowest_confidence_leg: str
    same_game: bool
    eligibility: Literal["theoretical", "verified"] = "theoretical"
    correlation_notes: str
    model_version: str


class Snapshot(Record):
    scope: Literal["game", "slate"] = "game"
    event_ids: list[str] = []
    run_id: str
    created_at: datetime
    season: int
    week: int
    game_id: str
    kickoff: datetime
    minutes_to_kickoff: float
    model_version: str
    data_cutoff: datetime
    provider_snapshot_ids: list[str]
    individual_predictions: list[Prediction]
    recommended_3_leg: list[Ticket]
    recommended_4_leg: list[Ticket]

    @model_validator(mode="after")
    def pregame(self):
        if self.created_at >= self.kickoff or self.data_cutoff > self.created_at:
            raise ValueError("official snapshots require pregame, non-future inputs")
        if any(p.line.collected_at > self.data_cutoff for p in self.individual_predictions):
            raise ValueError("line beyond data cutoff")
        return self


class Grade(Record):
    prediction_id: str
    actual: float | None
    result: Literal["win", "loss", "push", "pending", "void"]


class Results(Record):
    run_id: str
    created_at: datetime
    source_hash: str
    legs: list[Grade]
    tickets: list[dict]
