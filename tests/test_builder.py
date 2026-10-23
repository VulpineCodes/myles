from myles.schemas import TravelPreferences
from myles.providers import FixtureProvider
from myles.builder import build_itinerary
from myles.workflow import run_workflow

def test_builder_respects_budget_and_duration():
    prefs = TravelPreferences(origin="Nashville", destination="Lisbon", budget_usd=1800, duration_days=4, interests=["food","history"])
    result = run_workflow(prefs)
    assert result.ok and result.itinerary
    assert result.itinerary.total_cost_usd <= 1800
    assert result.itinerary.duration_days == 4
    assert result.itinerary.score_breakdown  # explainable scoring present
    assert result.itinerary.tradeoffs

def test_builder_returns_none_when_impossible():
    prefs = TravelPreferences(origin="Nashville", destination="Kyoto", budget_usd=200, duration_days=5)
    bundles = FixtureProvider().search("Nashville", "Kyoto", ["history"])
    assert build_itinerary(prefs, bundles) is None

def test_workflow_trace_covers_all_nodes_on_success():
    result = run_workflow(TravelPreferences(origin="Nashville", destination="Denver", budget_usd=900, duration_days=2, interests=["nature"]))
    assert result.trace == ["capture_preferences","gather_options","validate_constraints","build_itinerary","explain_tradeoffs","verify_grounding"]
