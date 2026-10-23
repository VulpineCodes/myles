"""Span-shaped tracing tests — 6 child spans, one trace_id, ERROR on failure,
optional real-OTEL export when the SDK is present."""
import json

import pytest

from myles.observability import (
    child_spans, export_spans_with_otel, otel_sdk_available,
)
from myles.providers import FailingProvider
from myles.schemas import TravelPreferences
from myles.workflow import NODES_ORDER, run_workflow

PREFS = TravelPreferences(origin="Nashville", destination="Lisbon", budget_usd=1800,
                          duration_days=4, interests=["food", "history"])


def test_run_produces_six_child_spans_under_one_trace_id():
    result = run_workflow(PREFS)
    assert result.trace_id and len(result.trace_id) == 32
    spans = result.spans
    assert spans, "no spans emitted"
    # All spans share one trace_id.
    assert {s["trace_id"] for s in spans} == {result.trace_id}
    # Exactly one root + exactly 6 children matching the 6 workflow nodes.
    roots = [s for s in spans if s["parent_span_id"] is None]
    children = child_spans(spans)
    assert len(roots) == 1 and roots[0]["name"] == "workflow_run"
    assert len(children) == 6
    assert [s["name"] for s in children] == NODES_ORDER
    for s in children:
        assert s["parent_span_id"] == roots[0]["span_id"]
        assert len(s["span_id"]) == 16
        assert s["status"]["code"] == "OK"
        assert "start_time_unix_nano" in s and "end_time_unix_nano" in s
        assert s["duration_ms"] >= 0
        # Required attributes present on every node span.
        assert "provider" in s["attributes"]
        assert "cache_hit" in s["attributes"]
        assert "constraint_result" in s["attributes"]
        assert s["attributes"]["provider"] == "fixture"
        assert s["attributes"]["constraint_result"] == "satisfied"
    # OTEL-shaped records must be JSON-serialisable as-is.
    json.dumps(spans)
    # Run log carries the same trace.
    assert result.run_log["trace_id"] == result.trace_id
    assert result.run_log["spans"] == spans


def test_gather_span_records_cache_hit_attribute():
    from myles.cache import InMemoryCache
    cache = InMemoryCache(default_ttl_seconds=300)
    run_workflow(PREFS, cache=cache)
    r2 = run_workflow(PREFS, cache=cache)
    gather = [s for s in child_spans(r2.spans) if s["name"] == "gather_options"][0]
    assert gather["attributes"]["cache_hit"] is True


def test_failure_run_marks_failing_span_error():
    result = run_workflow(PREFS, provider=FailingProvider())
    assert not result.ok
    children = child_spans(result.spans)
    by_name = {s["name"]: s for s in children}
    assert by_name["gather_options"]["status"]["code"] == "ERROR"
    # Root reflects the failure too; non-failing early node stays OK.
    root = [s for s in result.spans if s["parent_span_id"] is None][0]
    assert root["status"]["code"] == "ERROR"
    assert by_name["capture_preferences"]["status"]["code"] == "OK"
    assert {s["trace_id"] for s in result.spans} == {result.trace_id}


def test_invalid_input_marks_capture_span_error():
    bad = TravelPreferences(origin="Nashville", destination="Lisbon", budget_usd=1000,
                            duration_days=3, interests=["teleportation"], start_date="not-a-date")
    result = run_workflow(bad)
    assert not result.ok and result.errors
    by_name = {s["name"]: s for s in child_spans(result.spans)}
    assert by_name["capture_preferences"]["status"]["code"] == "ERROR"


def test_otel_exporter_path_when_sdk_present():
    if not otel_sdk_available():
        pytest.skip("opentelemetry-sdk not installed — JSON shape is the deliverable")
    result = run_workflow(PREFS, otel_export=True)
    assert result.otel_export is not None
    assert result.otel_export["otel_sdk"] is True
    # Root + 6 children re-emitted as real OTEL spans.
    assert result.otel_export["spans_exported"] == 7
    assert "gather_options" in result.otel_export["span_names"]
    # Direct helper agrees.
    direct = export_spans_with_otel(result.spans)
    assert direct is not None and direct["spans_exported"] == 7
