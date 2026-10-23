"""Structured run logging + span-shaped tracing.

Two layers, both dependency-free and JSON-serialisable:

1. **Run log** — one record per workflow run (nodes visited, provider,
   constraint result, latency, grounding, cache hit/miss). Attached to
   ``WorkflowResult.run_log`` and optionally pushed to a log sink.

2. **Span-shaped tracing** — per-node span records in an
   OpenTelemetry-*shaped* JSON structure::

       {
         "trace_id": "<32 hex>", "span_id": "<16 hex>",
         "parent_span_id": "<16 hex>" | None,
         "name": "gather_options",
         "start_time_unix_nano": ..., "end_time_unix_nano": ...,
         "duration_ms": 1.23,
         "attributes": {"provider": "fixture", "cache_hit": false,
                        "constraint_result": "satisfied"},
         "status": {"code": "OK" | "ERROR", "description": "..."}
       }

   A run produces one root span (``workflow_run``) plus one child span
   per workflow node (6 children), all sharing one ``trace_id``; child
   spans point at the root via ``parent_span_id``. A node that newly
   produces an error / unavailability is marked ``status.code=ERROR``.

   This is **OTEL-shaped, not OTEL-SDK by default** — no SDK is
   required to produce or consume these records. When
   ``opentelemetry-sdk`` *is* installed (verified installable in this
   sandbox: opentelemetry-sdk 1.45.1), ``export_spans_with_otel()``
   additionally re-emits the records as real OTEL spans through an
   in-memory exporter, and ``run_workflow(..., otel_export=True)`` /
   ``MYLES_OTEL_EXPORT=1`` enables that path per run. No OTLP collector
   is required for either path, and no collector export is claimed.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger("myles.workflow")

# ---------------------------------------------------------------------------
# OTEL SDK availability (optional exporter path)
# ---------------------------------------------------------------------------
try:  # pragma: no cover - environment dependent, exercised when present
    from opentelemetry.sdk.trace import TracerProvider as _OTelTracerProvider  # type: ignore
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor as _SimpleSpanProcessor  # type: ignore
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter as _InMemoryExporter  # type: ignore
    OTEL_SDK_AVAILABLE = True
except Exception:
    _OTelTracerProvider = None  # type: ignore
    _SimpleSpanProcessor = None  # type: ignore
    _InMemoryExporter = None  # type: ignore
    OTEL_SDK_AVAILABLE = False


def otel_sdk_available() -> bool:
    return OTEL_SDK_AVAILABLE


# ---------------------------------------------------------------------------
# Run log (original behaviour, extended with cache + trace fields)
# ---------------------------------------------------------------------------

def constraint_result_for(ok: bool, unavailable: Any, errors: list[str]) -> str:
    """Collapse a run outcome into one stable, queryable label."""
    if errors:
        return "error"
    if ok:
        return "satisfied"
    if unavailable is not None:
        return "unavailable"
    return "unavailable"


def build_run_log(
    *,
    trace: list[str],
    provider_used: str | None,
    ok: bool,
    unavailable: Any = None,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    latency_ms: float = 0.0,
    itinerary: Any = None,
    grounding: dict | None = None,
    cache_hit: bool | None = None,
    cache_hits: int = 0,
    cache_misses: int = 0,
    cache_enabled: bool = False,
    cache_backend: str | None = None,
    trace_id: str | None = None,
    spans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the structured record for one completed workflow run."""
    errors = errors or []
    record: dict[str, Any] = {
        "event": "workflow_run",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "nodes_visited": list(trace),
        # alias kept for callers that think of the graph trace
        "trace": list(trace),
        "provider_used": provider_used,
        "provider": provider_used,
        "constraint_result": constraint_result_for(ok, unavailable, errors),
        "latency_ms": round(float(latency_ms), 3),
        "ok": bool(ok),
        "errors": list(errors),
        "warnings_count": len(warnings or []),
        "grounding_ok": (grounding or {}).get("ok") if grounding else None,
        "destination": getattr(itinerary, "destination_name", None) if itinerary else None,
        "total_cost_usd": getattr(itinerary, "total_cost_usd", None) if itinerary else None,
        # --- cache (hardening sprint) ---
        "cache_enabled": bool(cache_enabled),
        "cache_hit": cache_hit,
        "cache_hits": int(cache_hits),
        "cache_misses": int(cache_misses),
        "cache_backend": cache_backend,
        # --- tracing (hardening sprint) ---
        "trace_id": trace_id,
        "spans": list(spans) if spans is not None else [],
    }
    return record


def emit_run_log(record: dict[str, Any], sink: Any = None) -> dict[str, Any]:
    """Deliver *record* to *sink* and return the record unchanged.

    Sink protocol:
      - ``None``          -> stdlib logging as one JSON line
      - ``list``          -> ``sink.append(record)``
      - callable          -> ``sink(record)``
      - file-like (.write)-> one JSON line written + flushed if possible
    """
    if sink is None:
        logger.info(json.dumps(record, default=str))
    elif isinstance(sink, list):
        sink.append(record)
    elif callable(sink):
        sink(record)  # type: ignore[operator]
    elif hasattr(sink, "write"):
        sink.write(json.dumps(record, default=str) + "\n")
        if hasattr(sink, "flush"):
            sink.flush()
    else:  # pragma: no cover - defensive
        raise TypeError(f"unsupported log sink type: {type(sink)!r}")
    return record


def run_log_to_json(record: dict[str, Any]) -> str:
    return json.dumps(record, default=str, sort_keys=True)


class _Timer:
    """Tiny perf-counter helper so workflow.py stays readable."""

    def __init__(self) -> None:
        self._t0 = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0


# ---------------------------------------------------------------------------
# Span-shaped tracing
# ---------------------------------------------------------------------------

def new_trace_id() -> str:
    """32 lowercase hex chars (128-bit), OTEL trace-id shape."""
    return secrets.token_hex(16)


def new_span_id() -> str:
    """16 lowercase hex chars (64-bit), OTEL span-id shape."""
    return secrets.token_hex(8)


def _status(code: str, description: str = "") -> dict[str, str]:
    s: dict[str, str] = {"code": code}
    if description:
        s["description"] = description
    return s


def make_span(*, trace_id: str, name: str, parent_span_id: str | None,
              start_ns: int, end_ns: int,
              attributes: dict[str, Any] | None = None,
              status_code: str = "OK", status_description: str = "") -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "span_id": new_span_id(),
        "parent_span_id": parent_span_id,
        "name": name,
        "start_time_unix_nano": int(start_ns),
        "end_time_unix_nano": int(end_ns),
        "duration_ms": round((int(end_ns) - int(start_ns)) / 1_000_000.0, 3),
        "attributes": dict(attributes or {}),
        "status": _status(status_code, status_description),
    }


def build_spans(*, trace_names: list[str],
                node_records: list[dict[str, Any]] | None = None,
                provider_used: str | None = None,
                constraint_result: str = "satisfied",
                cache_hit: bool | None = None,
                cache_enabled: bool = False,
                ok: bool = True,
                errors: list[str] | None = None,
                grounding: dict | None = None,
                destination: str | None = None,
                total_cost_usd: float | None = None,
                trace_id: str | None = None,
                root_start_ns: int | None = None,
                root_end_ns: int | None = None) -> dict[str, Any]:
    """Build ``{trace_id, root_span_id, spans}`` for one run.

    ``node_records`` (optional) is a list of per-node dicts with keys
    ``name``, ``start_ns``, ``end_ns``, ``error`` (bool),
    ``description`` and ``attributes`` — captured by the workflow loop
    for real timing. When omitted (e.g. the LangGraph path, where the
    graph owns timing), spans are synthesised from ``trace_names``
    with zero durations and status derived from the run outcome.
    Returns a dict so callers can store ``spans`` and ``trace_id``
    separately on the result.
    """
    trace_id = trace_id or new_trace_id()
    now_ns = time.time_ns()
    root_start = root_start_ns if root_start_ns is not None else now_ns
    root_end = root_end_ns if root_end_ns is not None else now_ns
    root_attributes: dict[str, Any] = {
        "provider": provider_used,
        "constraint_result": constraint_result,
        "cache_hit": cache_hit,
        "cache_enabled": bool(cache_enabled),
        "ok": bool(ok),
        "grounding_ok": (grounding or {}).get("ok") if grounding else None,
        "destination": destination,
        "total_cost_usd": total_cost_usd,
    }
    root = make_span(trace_id=trace_id, name="workflow_run", parent_span_id=None,
                     start_ns=root_start, end_ns=root_end,
                     attributes=root_attributes,
                     status_code="OK" if ok else "ERROR",
                     status_description="; ".join(errors or []) if not ok else "")
    root_span_id = root["span_id"]

    records: list[dict[str, Any]] = list(node_records) if node_records else [
        {"name": n, "start_ns": root_start, "end_ns": root_end,
         "error": False, "description": "", "attributes": {}}
        for n in trace_names
    ]
    # If synthesised and the run failed, mark the most plausible failing
    # node: gather_options for unavailability, verify_grounding for
    # grounding errors, capture_preferences for input errors.
    if not node_records and not ok:
        failing = None
        if errors and any("ungrounded" in e for e in (errors or [])):
            failing = "verify_grounding"
        elif errors:
            failing = "capture_preferences"
        elif constraint_result == "unavailable":
            failing = "gather_options"
        for r in records:
            if r["name"] == failing:
                r["error"] = True
                r["description"] = "; ".join(errors or []) or constraint_result

    children: list[dict[str, Any]] = []
    for r in records:
        attrs: dict[str, Any] = {
            "provider": provider_used,
            "constraint_result": constraint_result,
            "cache_hit": cache_hit,
            "cache_enabled": bool(cache_enabled),
        }
        # Node-specific attributes override / extend the common set.
        attrs.update(r.get("attributes") or {})
        children.append(make_span(
            trace_id=trace_id, name=r["name"], parent_span_id=root_span_id,
            start_ns=r.get("start_ns", root_start), end_ns=r.get("end_ns", root_end),
            attributes=attrs,
            status_code="ERROR" if r.get("error") else "OK",
            status_description=r.get("description", "") if r.get("error") else "",
        ))
    return {"trace_id": trace_id, "root_span_id": root_span_id, "spans": [root] + children}


def child_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The per-node (non-root) spans from a full span list."""
    return [s for s in spans if s.get("parent_span_id") is not None]


# ---------------------------------------------------------------------------
# Optional real-OTEL exporter path (only when the SDK is installed)
# ---------------------------------------------------------------------------

def export_spans_with_otel(spans: list[dict[str, Any]],
                           service_name: str = "myles") -> dict[str, Any] | None:
    """Re-emit span-shaped records as real OTEL spans. Optional path.

    Returns ``None`` when the OTEL SDK is not installed (the JSON shape
    remains the deliverable). When the SDK *is* present, spans are
    created through a real ``TracerProvider`` with an in-memory
    exporter and the exported span names/count are returned — this
    proves the shape maps onto real OTEL without needing a collector.
    """
    if not OTEL_SDK_AVAILABLE:  # pragma: no cover - env dependent
        return None
    from opentelemetry import trace as _otel_trace  # type: ignore
    from opentelemetry.trace import Status, StatusCode  # type: ignore

    exporter = _InMemoryExporter()
    provider = _OTelTracerProvider()
    provider.add_span_processor(_SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer(service_name)
    # Map our span_ids so parent/child relationships are real OTEL
    # contexts, not just equal-looking strings.
    contexts: dict[str, Any] = {}
    for s in spans:
        parent_ctx = contexts.get(s.get("parent_span_id")) if s.get("parent_span_id") else None
        with tracer.start_as_current_span(
            s["name"],
            context=parent_ctx,
            start_time=int(s["start_time_unix_nano"]),
            attributes={k: v for k, v in (s.get("attributes") or {}).items() if v is not None},
        ) as otel_span:
            otel_span.set_status(Status(
                StatusCode.ERROR if (s.get("status") or {}).get("code") == "ERROR" else StatusCode.OK,
                (s.get("status") or {}).get("description", ""),
            ))
            otel_span.end(end_time=int(s["end_time_unix_nano"]))
            contexts[s["span_id"]] = _otel_trace.set_span_in_context(otel_span)
    provider.force_flush()
    exported = exporter.get_finished_spans()
    return {"exporter": "in_memory", "otel_sdk": True,
            "spans_exported": len(exported),
            "span_names": [sp.name for sp in exported]}
