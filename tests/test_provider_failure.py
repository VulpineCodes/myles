from myles.schemas import TravelPreferences
from myles.providers import FailingProvider, EmptyProvider
from myles.workflow import run_workflow
from myles.explainer import LLMExplainer
import pytest

PREFS = TravelPreferences(origin="Nashville", budget_usd=1500, duration_days=4)

def test_failing_provider_graceful_structured_result():
    r = run_workflow(PREFS, provider=FailingProvider())
    assert not r.ok and r.itinerary is None
    assert r.unavailable is not None and r.unavailable.kind == "provider_unavailable"
    assert "invent" in r.unavailable.fallback_message or "will not invent" in r.unavailable.fallback_message

def test_empty_provider_graceful():
    r = run_workflow(PREFS, provider=EmptyProvider())
    assert r.itinerary is None and r.unavailable is not None

def test_unknown_destination_no_fabrication():
    r = run_workflow(TravelPreferences(origin="Nashville", destination="Atlantis", budget_usd=1500, duration_days=4))
    assert r.itinerary is None and r.unavailable is not None

def test_llm_explainer_disabled_without_key(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        LLMExplainer(api_key="").explain(itin=None)  # type: ignore
