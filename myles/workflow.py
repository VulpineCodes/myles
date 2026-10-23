"""Explicit state-graph workflow (primary implementation, no LangGraph needed).

Nodes: capture_preferences → gather_options → validate_constraints →
build_itinerary → explain_tradeoffs → verify_grounding

State is a plain dict threaded through nodes; each node is a pure-ish
function (state) -> state, recorded in state['trace'] so tool selection
is auditable. Failures produce a structured result, never invented data.

Hardening (cache + spans):
  - ``gather_options`` optionally consults a ``ProviderCache``
    (see ``myles/cache.py``) keyed by (provider, origin, destination).
    A hit skips the provider call entirely; a miss populates the cache.
    Cached bundles still pass through constraint validation, building
    and grounding — the cache never bypasses grounding.
  - Every run records per-node span records (OTEL-shaped JSON, see
    ``myles/observability.py``) plus cache hit/miss in its run log.
"""
from __future__ import annotations
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from .schemas import TravelPreferences, validate_preferences, ProviderUnavailable, Itinerary
from .providers import TravelProvider, ProviderError, FixtureProvider
from .validator import validate_bundle_feasibility, validate_itinerary
from .builder import build_itinerary
from .explainer import Explainer, DeterministicExplainer
from .grounding import check_grounding

@dataclass
class WorkflowResult:
    ok: bool
    itinerary: Itinerary | None = None
    unavailable: ProviderUnavailable | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    grounding: dict | None = None
    trace: list[str] = field(default_factory=list)
    # Observability (see myles/observability.py)
    run_log: dict | None = None
    latency_ms: float | None = None
    provider_used: str | None = None
    # Cache (see myles/cache.py)
    cache_hit: bool | None = None
    cache_hits: int = 0
    cache_misses: int = 0
    cache_enabled: bool = False
    # Span-shaped tracing (see myles/observability.py)
    spans: list[dict] = field(default_factory=list)
    trace_id: str | None = None
    otel_export: dict | None = None
    def to_dict(self):
        return {"ok": self.ok,
                "itinerary": self.itinerary.to_dict() if self.itinerary else None,
                "unavailable": self.unavailable.to_dict() if self.unavailable else None,
                "errors": self.errors, "warnings": self.warnings,
                "grounding": self.grounding, "trace": self.trace,
                "run_log": self.run_log, "latency_ms": self.latency_ms,
                "provider_used": self.provider_used,
                "cache_hit": self.cache_hit, "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses, "cache_enabled": self.cache_enabled,
                "spans": self.spans, "trace_id": self.trace_id,
                "otel_export": self.otel_export}

def node_capture_preferences(state):
    state["trace"].append("capture_preferences")
    prefs: TravelPreferences = state["prefs"]
    errs = validate_preferences(prefs)
    state["errors"].extend(errs)
    return state

def make_node_gather(provider: TravelProvider, cache: Any = None, cache_ttl_seconds: float | None = None):
    def node(state):
        state["trace"].append("gather_options")
        state["tool_used"] = provider.name
        prefs = state["prefs"]
        bundles = None
        # --- cache lookup (behind the provider interface) ---
        if cache is not None:
            from .cache import make_cache_key, NullCache
            if not isinstance(cache, NullCache):
                state["cache_enabled"] = True
                state["cache_backend"] = getattr(cache, "backend", None)
                key = make_cache_key(provider.name, prefs.origin, prefs.destination)
                state["cache_key"] = key
                try:
                    cached = cache.get(key)
                except Exception:
                    cached = None  # a broken cache must not break planning
                if cached is not None:
                    bundles = cached
                    state["cache_hit"] = True
                    state["cache_hits"] = int(state.get("cache_hits", 0)) + 1
                else:
                    state["cache_hit"] = False
                    state["cache_misses"] = int(state.get("cache_misses", 0)) + 1
        if bundles is None:
            try:
                bundles = provider.search(prefs.origin, prefs.destination, prefs.interests)
            except ProviderError as e:
                state["unavailable"] = ProviderUnavailable(reason=str(e), destination_hint=prefs.destination)
                bundles = []
            else:
                # Populate cache on a miss (only for real results, and
                # never for an error — the except branch skips this).
                if cache is not None and state.get("cache_enabled"):
                    try:
                        from .cache import make_cache_key
                        cache.set(make_cache_key(provider.name, prefs.origin, prefs.destination),
                                  bundles, ttl_seconds=cache_ttl_seconds)
                    except Exception:
                        pass
        if not bundles and state.get("unavailable") is None:
            state["unavailable"] = ProviderUnavailable(reason="provider returned no options", destination_hint=prefs.destination)
        state["bundles"] = bundles
        return state
    return node

def node_validate_constraints(state):
    state["trace"].append("validate_constraints")
    if state.get("unavailable"): return state
    feasible = []
    for b in state["bundles"]:
        v = validate_bundle_feasibility(state["prefs"], b)
        if v.ok: feasible.append(b)
        else: state["warnings"].extend([f"{b.destination.name}: {x}" for x in v.hard_violations])
    state["bundles"] = feasible
    if not feasible:
        state["unavailable"] = ProviderUnavailable(reason="no destination satisfies hard constraints (budget/duration)", destination_hint=state["prefs"].destination)
    return state

def node_build_itinerary(state):
    state["trace"].append("build_itinerary")
    if state.get("unavailable"): return state
    itin = build_itinerary(state["prefs"], state["bundles"])
    if itin is None:
        state["unavailable"] = ProviderUnavailable(reason="could not build an itinerary within hard constraints", destination_hint=state["prefs"].destination)
    state["itinerary"] = itin
    return state

def make_node_explain(explainer: Explainer):
    def node(state):
        state["trace"].append("explain_tradeoffs")
        if state.get("itinerary"): state["itinerary"].tradeoffs = explainer.explain(state["itinerary"])
        return state
    return node

def node_verify_grounding(state):
    state["trace"].append("verify_grounding")
    if state.get("itinerary"):
        known: set[str] = set()
        for b in state["bundles"]: known |= b.all_ids()
        report = check_grounding(state["itinerary"], known)
        state["grounding"] = report.to_dict()
        if not report.ok: state["errors"].append(f"ungrounded claims: {report.ungrounded}")
    return state

NODES_ORDER = ["capture_preferences","gather_options","validate_constraints","build_itinerary","explain_tradeoffs","verify_grounding"]

def _resolve_cache(cache: Any, cache_enabled: bool | None, cache_ttl_seconds: float | None):
    """Return (effective_cache_or_None, enabled_bool)."""
    from .cache import NullCache, get_default_cache
    if cache is not None:
        if isinstance(cache, NullCache):
            return None, False
        return cache, True
    if cache_enabled is False:
        return None, False
    if cache_enabled is True:
        c = get_default_cache(enabled=True, ttl_seconds=cache_ttl_seconds)
        return (None, False) if isinstance(c, NullCache) else (c, True)
    # cache_enabled is None: honour env (MYLES_CACHE_ENABLED), else off.
    c = get_default_cache(enabled=None, ttl_seconds=cache_ttl_seconds)
    if isinstance(c, NullCache):
        return None, False
    return c, True

def run_workflow(prefs: TravelPreferences, provider: TravelProvider | None = None, explainer: Explainer | None = None,
                 store: Any = None, user_id: str | None = None, log_sink: Any = None,
                 cache: Any = None, cache_enabled: bool | None = None,
                 cache_ttl_seconds: float | None = None,
                 otel_export: bool | None = None) -> WorkflowResult:
    """Run the planner graph.

    Optional integrations (off by default unless noted, existing
    callers unchanged):
      - ``store`` + ``user_id``: persist preferences and append this plan
        to the user's itinerary history via a TravelStore adapter
        (tested adapter: myles.store.SQLiteStore).
      - ``log_sink``: receive the structured run-log record.
      - ``cache`` / ``cache_enabled`` / ``cache_ttl_seconds``: provider-
        response cache for ``gather_options`` (see myles/cache.py).
        Pass a ``ProviderCache`` instance to share a cache across runs
        (that sharing is what makes a second identical run a hit), or
        ``cache_enabled=True`` for a fresh default cache, or set
        ``MYLES_CACHE_ENABLED=1``. Disabled = identical behaviour,
        provider called every run.
      - ``otel_export``: when True (or ``MYLES_OTEL_EXPORT=1``) and the
        OTEL SDK is installed, also re-emit spans as real OTEL spans
        via an in-memory exporter; result in ``result.otel_export``.
    """
    from .observability import build_run_log, emit_run_log, _Timer, build_spans, constraint_result_for, export_spans_with_otel
    timer = _Timer()
    provider = provider or FixtureProvider()
    explainer = explainer or DeterministicExplainer()
    effective_cache, cache_on = _resolve_cache(cache, cache_enabled, cache_ttl_seconds)
    state: dict[str, Any] = {"prefs": prefs, "trace": [], "errors": [], "warnings": [], "bundles": [], "itinerary": None, "unavailable": None, "grounding": None, "tool_used": None,
                             "cache_hit": None, "cache_hits": 0, "cache_misses": 0, "cache_enabled": cache_on, "cache_backend": getattr(effective_cache, "backend", None) if effective_cache else None, "cache_key": None}
    nodes: list[Callable] = [node_capture_preferences, make_node_gather(provider, cache=effective_cache, cache_ttl_seconds=cache_ttl_seconds), node_validate_constraints, node_build_itinerary, make_node_explain(explainer), node_verify_grounding]
    node_names = list(NODES_ORDER)
    node_records: list[dict[str, Any]] = []
    root_start_ns = time.time_ns()
    for n, node_name in zip(nodes, node_names):
        start_ns = time.time_ns()
        t0 = time.perf_counter()
        errors_before = list(state["errors"])
        unavailable_before = state.get("unavailable")
        warnings_before = list(state["warnings"])
        state = n(state)
        end_ns = time.time_ns()
        new_errors = state["errors"][len(errors_before):]
        newly_unavailable = state.get("unavailable") is not None and unavailable_before is None
        is_error = bool(new_errors) or newly_unavailable
        # gather_options provider failure is an error span; a later node
        # merely propagating that unavailability is not itself failing.
        attrs: dict[str, Any] = {"duration_ms": round((time.perf_counter() - t0) * 1000.0, 3)}
        if node_name == "gather_options":
            attrs.update({"cache_hit": state.get("cache_hit"), "cache_enabled": bool(state.get("cache_enabled")),
                          "bundles": len(state.get("bundles") or [])})
        if node_name == "validate_constraints":
            attrs.update({"feasible_bundles": len(state.get("bundles") or [])})
        if node_name == "verify_grounding":
            attrs.update({"grounding_ok": (state.get("grounding") or {}).get("ok") if state.get("grounding") else None})
        node_records.append({"name": node_name, "start_ns": start_ns, "end_ns": end_ns,
                             "error": is_error,
                             "description": "; ".join(new_errors) or (getattr(state.get("unavailable"), "reason", "") if newly_unavailable else ""),
                             "attributes": attrs})
        if state["errors"] and "capture_preferences" in state["trace"] and state["trace"][-1]=="capture_preferences":
            break
    root_end_ns = time.time_ns()
    ok = state["itinerary"] is not None and not state["errors"] and (state["grounding"] is None or state["grounding"]["ok"])
    latency_ms = timer.elapsed_ms()
    provider_used = state.get("tool_used") or getattr(provider, "name", None)
    c_result = constraint_result_for(ok, state["unavailable"], state["errors"])
    # For synthesised node records, validate/build spans that only
    # propagated an earlier unavailability should not all read ERROR:
    # build_spans uses our explicit per-node error flags here, which
    # already encode that (only the node that *newly* set unavailable
    # or added errors is flagged).
    span_info = build_spans(trace_names=state["trace"], node_records=node_records,
        provider_used=provider_used, constraint_result=c_result,
        cache_hit=state.get("cache_hit"), cache_enabled=bool(state.get("cache_enabled")),
        ok=ok, errors=state["errors"], grounding=state["grounding"],
        destination=getattr(state["itinerary"], "destination_name", None) if state["itinerary"] else None,
        total_cost_usd=getattr(state["itinerary"], "total_cost_usd", None) if state["itinerary"] else None,
        root_start_ns=root_start_ns, root_end_ns=root_end_ns)
    spans = span_info["spans"]; trace_id = span_info["trace_id"]
    run_log = build_run_log(trace=state["trace"], provider_used=provider_used, ok=ok,
        unavailable=state["unavailable"], errors=state["errors"], warnings=state["warnings"],
        latency_ms=latency_ms, itinerary=state["itinerary"], grounding=state["grounding"],
        cache_hit=state.get("cache_hit"), cache_hits=int(state.get("cache_hits", 0)),
        cache_misses=int(state.get("cache_misses", 0)), cache_enabled=bool(state.get("cache_enabled")),
        cache_backend=state.get("cache_backend"), trace_id=trace_id, spans=spans)
    # Optional real-OTEL export (no-op returning None without the SDK)
    want_otel = otel_export if otel_export is not None else os.environ.get("MYLES_OTEL_EXPORT", "").strip().lower() in {"1", "true", "yes", "on"}
    otel_result = None
    if want_otel:
        try:
            otel_result = export_spans_with_otel(spans)
        except Exception as e:  # exporter must never break planning
            otel_result = {"otel_sdk": True, "error": str(e), "spans_exported": 0}
        run_log["otel_export"] = otel_result
    result = WorkflowResult(ok=ok, itinerary=state["itinerary"], unavailable=state["unavailable"],
        errors=state["errors"], warnings=state["warnings"], grounding=state["grounding"], trace=state["trace"],
        run_log=run_log, latency_ms=run_log["latency_ms"], provider_used=provider_used,
        cache_hit=state.get("cache_hit"), cache_hits=int(state.get("cache_hits", 0)),
        cache_misses=int(state.get("cache_misses", 0)), cache_enabled=bool(state.get("cache_enabled")),
        spans=spans, trace_id=trace_id, otel_export=otel_result)
    if log_sink is not None:
        emit_run_log(run_log, log_sink)
    if store is not None:
        effective_user = user_id or "anonymous"
        try:
            store.save_preferences(effective_user, prefs)
            store.save_result(effective_user, result, prefs=prefs)
        except Exception as e:  # persistence must not fake a planning failure, but must be visible
            result.warnings.append(f"persistence failed: {e}")
    return result
