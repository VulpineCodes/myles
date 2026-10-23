"""FastAPI boundary. Imports the deterministic core; converts HTTP <-> dataclasses.
Run: uvicorn myles.api.app:app --reload   (requires fastapi, uvicorn, pydantic)
Core logic has no FastAPI dependency, so tests run without it.
"""
from __future__ import annotations
try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except Exception as e:  # pragma: no cover
    raise ImportError("FastAPI app requires: pip install -r requirements.txt") from e

from ..schemas import TravelPreferences
from ..providers import FixtureProvider
from ..workflow import run_workflow

app = FastAPI(title="Myles — Travel Intelligence Assistant", version="0.1.0")
provider = FixtureProvider()  # fixture by default; swap with a live adapter when keys exist

class TripRequest(BaseModel):
    origin: str
    destination: str | None = None
    budget_usd: float = 1500.0
    start_date: str = "2026-11-10"
    duration_days: int = 4
    travelers: int = 1
    interests: list[str] = ["food", "history"]
    transport_preferences: list[str] = ["flight"]
    max_lodging_per_night_usd: float | None = None

@app.get("/health")
def health(): return {"status": "ok", "provider": provider.name, "provenance": "fixture"}

@app.get("/destinations")
def destinations(): return [d.to_dict() for d in provider.list_destinations()]

@app.post("/plan")
def plan(req: TripRequest):
    prefs = TravelPreferences(**req.model_dump())
    result = run_workflow(prefs, provider=provider)
    return result.to_dict()
