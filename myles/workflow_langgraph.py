"""LangGraph adapter — the same nodes as workflow.py, run on LangGraph.

Status (verified 2026-10-22): ``pip install langgraph`` succeeded on
retry in this sandbox (langgraph 1.2.16, ~25s, from cache + network)
after the foundation attempt timed out. ``build_langgraph()`` builds a
real ``StateGraph`` from the *real* node functions in ``workflow.py``
(no copies), compiles it, and ``run_langgraph_workflow()`` invokes it
end-to-end. ``tests/test_langgraph_parity.py`` asserts the graph's
Lisbon itinerary matches the plain workflow exactly (destination,
cost, record ids, citations, grounding, trace). The test skips — it
does not fail — when langgraph is not installed, and the plain graph
in ``workflow.py`` remains the dependency-free primary implementation.

Hardening: accepts the same ``cache=`` as the plain workflow (the
``gather_options`` node is shared, so caching behaves identically)
and attaches OTEL-shaped spans synthesised from the graph trace
(the graph owns node timing, so durations are 0 in this path —
the plain workflow records real per-node timing).
"""
from __future__ import annotations
try:
    from langgraph.graph import StateGraph, END  # type: ignore
    LANGGRAPH_AVAILABLE = True
except Exception:
    LANGGRAPH_AVAILABLE = False

from . import workflow as W


def build_langgraph(provider=None, explainer=None, cache=None, cache_ttl_seconds=None):
    if not LANGGRAPH_AVAILABLE:
        raise ImportError("langgraph not installed — use myles.workflow.run_workflow (primary implementation)")
    # Real wiring using the same node functions as workflow.py.
    from .providers import FixtureProvider
    from .explainer import DeterministicExplainer
    provider = provider or FixtureProvider(); explainer = explainer or DeterministicExplainer()
    g = StateGraph(dict)
    g.add_node("capture_preferences", W.node_capture_preferences)
    g.add_node("gather_options", W.make_node_gather(provider, cache=cache, cache_ttl_seconds=cache_ttl_seconds))
    g.add_node("validate_constraints", W.node_validate_constraints)
    g.add_node("build_itinerary", W.node_build_itinerary)
    g.add_node("explain_tradeoffs", W.make_node_explain(explainer))
    g.add_node("verify_grounding", W.node_verify_grounding)
    g.set_entry_point("capture_preferences")
    for a, b in zip(W.NODES_ORDER, W.NODES_ORDER[1:]): g.add_edge(a, b)
    g.add_edge("verify_grounding", END)
    return g.compile()


def run_langgraph_workflow(prefs, provider=None, explainer=None, cache=None, cache_ttl_seconds=None) -> W.WorkflowResult:
    """Invoke the compiled LangGraph and return a WorkflowResult.

    Same result shape as ``workflow.run_workflow`` so callers and the
    parity test can compare the two implementations directly.
    """
    if not LANGGRAPH_AVAILABLE:
        raise ImportError("langgraph not installed — use myles.workflow.run_workflow (primary implementation)")
    from .observability import build_spans, build_run_log, constraint_result_for
    graph = build_langgraph(provider=provider, explainer=explainer, cache=cache, cache_ttl_seconds=cache_ttl_seconds)
    state = {"prefs": prefs, "trace": [], "errors": [], "warnings": [], "bundles": [],
             "itinerary": None, "unavailable": None, "grounding": None, "tool_used": None,
             "cache_hit": None, "cache_hits": 0, "cache_misses": 0,
             "cache_enabled": cache is not None, "cache_backend": getattr(cache, "backend", None) if cache else None, "cache_key": None}
    out = graph.invoke(state)
    ok = (
        out.get("itinerary") is not None
        and not out.get("errors")
        and (out.get("grounding") is None or out["grounding"]["ok"])
    )
    c_result = constraint_result_for(ok, out.get("unavailable"), list(out.get("errors") or []))
    span_info = build_spans(trace_names=list(out.get("trace") or []),
        provider_used=out.get("tool_used"), constraint_result=c_result,
        cache_hit=out.get("cache_hit"), cache_enabled=bool(out.get("cache_enabled")),
        ok=ok, errors=list(out.get("errors") or []), grounding=out.get("grounding"),
        destination=getattr(out.get("itinerary"), "destination_name", None) if out.get("itinerary") else None,
        total_cost_usd=getattr(out.get("itinerary"), "total_cost_usd", None) if out.get("itinerary") else None)
    run_log = build_run_log(trace=list(out.get("trace") or []), provider_used=out.get("tool_used"), ok=ok,
        unavailable=out.get("unavailable"), errors=list(out.get("errors") or []),
        warnings=list(out.get("warnings") or []), latency_ms=0.0,
        itinerary=out.get("itinerary"), grounding=out.get("grounding"),
        cache_hit=out.get("cache_hit"), cache_hits=int(out.get("cache_hits", 0)),
        cache_misses=int(out.get("cache_misses", 0)), cache_enabled=bool(out.get("cache_enabled")),
        cache_backend=out.get("cache_backend"), trace_id=span_info["trace_id"], spans=span_info["spans"])
    return W.WorkflowResult(
        ok=ok,
        itinerary=out.get("itinerary"),
        unavailable=out.get("unavailable"),
        errors=list(out.get("errors") or []),
        warnings=list(out.get("warnings") or []),
        grounding=out.get("grounding"),
        trace=list(out.get("trace") or []),
        run_log=run_log,
        provider_used=out.get("tool_used"),
        cache_hit=out.get("cache_hit"), cache_hits=int(out.get("cache_hits", 0)),
        cache_misses=int(out.get("cache_misses", 0)), cache_enabled=bool(out.get("cache_enabled")),
        spans=span_info["spans"], trace_id=span_info["trace_id"],
    )
