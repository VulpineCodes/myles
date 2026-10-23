"""Observability tests — every run produces a structured trace record."""
import json

from myles.schemas import TravelPreferences
from myles.workflow import run_workflow, NODES_ORDER
from myles.observability import build_run_log, emit_run_log, run_log_to_json
from myles.providers import FailingProvider

PREFS = TravelPreferences(origin="Nashville", destination="Lisbon", budget_usd=1800,
                          duration_days=4, interests=["food", "history"])


def test_run_produces_trace_record_with_all_nodes():
    result = run_workflow(PREFS)
    log = result.run_log
    assert log is not None
    assert log["event"] == "workflow_run"
    assert log["nodes_visited"] == NODES_ORDER
    # Every node name from the graph appears in the record.
    for node in NODES_ORDER:
        assert node in log["nodes_visited"]
    assert log["provider_used"] == "fixture"
    assert log["constraint_result"] == "satisfied"
    assert isinstance(log["latency_ms"], (int, float)) and log["latency_ms"] >= 0
    assert result.latency_ms == log["latency_ms"]
    assert result.provider_used == "fixture"
    # The record must be JSON-serialisable as-is (structured logging).
    json.loads(run_log_to_json(log))


def test_log_sink_list_receives_record():
    sink: list = []
    result = run_workflow(PREFS, log_sink=sink)
    assert len(sink) == 1
    assert sink[0] is result.run_log or sink[0] == result.run_log
    assert sink[0]["nodes_visited"] == NODES_ORDER


def test_log_sink_callable_receives_record():
    seen: list = []
    run_workflow(PREFS, log_sink=lambda rec: seen.append(rec))
    assert len(seen) == 1 and seen[0]["provider_used"] == "fixture"


def test_failure_run_still_produces_trace_record():
    sink: list = []
    result = run_workflow(PREFS, provider=FailingProvider(), log_sink=sink)
    assert not result.ok
    log = result.run_log
    assert log is not None
    assert log["provider_used"] == "failing-fixture"
    assert log["constraint_result"] == "unavailable"
    assert "gather_options" in log["nodes_visited"]
    assert len(sink) == 1


def test_build_and_emit_run_log_units():
    record = build_run_log(trace=NODES_ORDER, provider_used="fixture", ok=True, latency_ms=2.5)
    assert record["constraint_result"] == "satisfied"
    out: list = []
    assert emit_run_log(record, out) is record
    assert out == [record]
    assert json.loads(run_log_to_json(record))["nodes_visited"] == NODES_ORDER
