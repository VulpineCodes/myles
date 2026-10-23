"""Schemas for Myles — dataclasses + explicit validation.

Pydantic is listed in requirements and used at the API boundary (api/app.py
converts to/from these dataclasses). The core uses dataclasses so it runs
and tests fully offline with the stdlib only — no heavy install required.
Every provider record carries `source` and `provenance` so fixture data
can never be mistaken for live data.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any

ALLOWED_INTERESTS = {"food","history","art","nature","nightlife","family","adventure","relaxation","music","architecture"}
ALLOWED_TRANSPORT = {"flight","train","bus","car","any"}

@dataclass
class TravelPreferences:
    origin: str
    destination: str | None = None  # hint; None = let planner choose best fixture match
    budget_usd: float = 1500.0
    start_date: str = "2026-11-10"  # ISO date
    duration_days: int = 4
    travelers: int = 1
    interests: list[str] = field(default_factory=lambda: ["food","history"])
    transport_preferences: list[str] = field(default_factory=lambda: ["flight"])
    max_lodging_per_night_usd: float | None = None

    def to_dict(self): return asdict(self)

def validate_preferences(p: TravelPreferences) -> list[str]:
    errors: list[str] = []
    if not p.origin or not p.origin.strip(): errors.append("origin is required")
    if p.budget_usd is None or p.budget_usd <= 0: errors.append("budget_usd must be > 0")
    if p.duration_days < 1 or p.duration_days > 30: errors.append("duration_days must be 1..30")
    if p.travelers < 1 or p.travelers > 10: errors.append("travelers must be 1..10")
    try:
        date.fromisoformat(p.start_date)
    except Exception:
        errors.append("start_date must be ISO YYYY-MM-DD")
    for i in p.interests:
        if i not in ALLOWED_INTERESTS: errors.append(f"unknown interest: {i}")
    for t in p.transport_preferences:
        if t not in ALLOWED_TRANSPORT: errors.append(f"unknown transport: {t}")
    if p.max_lodging_per_night_usd is not None and p.max_lodging_per_night_usd <= 0:
        errors.append("max_lodging_per_night_usd must be > 0")
    return errors

@dataclass
class Destination:
    id: str; name: str; country: str; description: str
    tags: list[str] = field(default_factory=list)
    source: str = "fixture"; provenance: str = "fixture"
    def to_dict(self): return asdict(self)

@dataclass
class FlightOption:
    id: str; destination_id: str; origin: str; carrier: str
    price_usd: float; duration_hours: float; transport_type: str = "flight"
    source: str = "fixture"; provenance: str = "fixture"
    def to_dict(self): return asdict(self)

@dataclass
class LodgingOption:
    id: str; destination_id: str; name: str; price_per_night_usd: float; rating: float
    tags: list[str] = field(default_factory=list)
    source: str = "fixture"; provenance: str = "fixture"
    def to_dict(self): return asdict(self)

@dataclass
class ActivityOption:
    id: str; destination_id: str; name: str; price_usd: float; rating: float
    tags: list[str] = field(default_factory=list)
    source: str = "fixture"; provenance: str = "fixture"
    def to_dict(self): return asdict(self)

@dataclass
class ProviderBundle:
    destination: Destination
    flights: list[FlightOption] = field(default_factory=list)
    lodging: list[LodgingOption] = field(default_factory=list)
    activities: list[ActivityOption] = field(default_factory=list)
    def all_ids(self) -> set[str]:
        ids = {self.destination.id}
        ids |= {x.id for x in self.flights}; ids |= {x.id for x in self.lodging}; ids |= {x.id for x in self.activities}
        return ids
    def to_dict(self):
        return {"destination": self.destination.to_dict(),
                "flights": [x.to_dict() for x in self.flights],
                "lodging": [x.to_dict() for x in self.lodging],
                "activities": [x.to_dict() for x in self.activities]}

@dataclass
class Claim:
    text: str
    record_ids: list[str] = field(default_factory=list)
    def to_dict(self): return asdict(self)

@dataclass
class Tradeoff:
    factor: str; detail: str; score_contribution: float = 0.0
    def to_dict(self): return asdict(self)

@dataclass
class Itinerary:
    destination_id: str; destination_name: str
    flight_id: str | None; lodging_id: str | None
    activity_ids: list[str] = field(default_factory=list)
    duration_days: int = 0; total_cost_usd: float = 0.0
    score: float = 0.0; score_breakdown: dict[str, float] = field(default_factory=dict)
    tradeoffs: list[Tradeoff] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)  # provider record ids
    provenance: str = "fixture"
    def to_dict(self):
        d = asdict(self); return d

@dataclass
class ProviderUnavailable:
    kind: str = "provider_unavailable"
    reason: str = ""
    destination_hint: str | None = None
    fallback_message: str = "No verified options available. Myles will not invent prices or availability — try another destination or retry later."
    def to_dict(self): return asdict(self)

@dataclass
class ValidationResult:
    ok: bool
    hard_violations: list[str] = field(default_factory=list)
    soft_warnings: list[str] = field(default_factory=list)
    interest_match_ratio: float = 0.0
    def to_dict(self): return asdict(self)
