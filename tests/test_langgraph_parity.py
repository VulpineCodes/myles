"""LangGraph parity — the LangGraph graph must produce the same
grounded Lisbon itinerary as the plain workflow. Skips (never fails)
when langgraph is not installed."""
import pytest

from myles.schemas import TravelPreferences
from myles.workflow import run_workflow

pytest.importorskip("langgraph", reason="langgraph not installed — plain workflow is primary")

from myles.workflow_langgraph import LANGGRAPH_AVAILABLE, build_langgraph, run_langgraph_workflow  # noqa: E402

PREFS = TravelPreferences(origin="Nashville", destination="Lisbon", budget_usd=1800,
                          duration_days=4, interests=["food", "history"])


def test_langgraph_is_available_and_compiles():
    assert LANGGRAPH_AVAILABLE
    graph = build_langgraph()
    assert graph is not None


def test_langgraph_lisbon_matches_plain_workflow():
    plain = run_workflow(PREFS)
    lg = run_langgraph_workflow(PREFS)
    assert lg.ok and plain.ok
    assert lg.trace == plain.trace
    assert lg.itinerary is not None and plain.itinerary is not None
    assert lg.itinerary.destination_id == plain.itinerary.destination_id == "dest_lisbon"
    assert lg.itinerary.destination_name == plain.itinerary.destination_name
    assert lg.itinerary.total_cost_usd == plain.itinerary.total_cost_usd == 855.0
    assert lg.itinerary.flight_id == plain.itinerary.flight_id
    assert lg.itinerary.lodging_id == plain.itinerary.lodging_id
    assert lg.itinerary.activity_ids == plain.itinerary.activity_ids
    assert lg.itinerary.citations == plain.itinerary.citations
    assert lg.itinerary.score == plain.itinerary.score
    assert lg.grounding is not None and lg.grounding["ok"]
