# Architecture — Myles

## Deterministic vs model reasoning

The split is the design. Anything that can be checked — budgets, durations, prices, record existence — is deterministic code. Model reasoning, when it exists at all, is confined to one interface and its output must pass the same checks as everything else.

| Layer | Deterministic | Model (optional, off by default) |
|---|---|---|
| Preferences | Schema + `validate_preferences` | — |
| Gathering | Provider adapters return records with ids + provenance | — |
| Constraints | `validator.py` hard-rejects violations | — |
| Building | `builder.py` scoring: 0.45 cost, 0.35 interest, 0.20 rating | — |
| Explaining | `DeterministicExplainer` (templates + score breakdown) | `LLMExplainer` stub behind `Explainer` interface; requires `MODEL_API_KEY` |
| Grounding | `grounding.py` verifies every claim's record ids | LLM output would be ground-checked the same way before use |

## Workflow graph

`workflow.py` threads a state dict through six nodes, recording each in `trace`:
`capture_preferences → gather_options → validate_constraints → build_itinerary → explain_tradeoffs → verify_grounding`.
`workflow_langgraph.py` wires these identical node functions into a LangGraph `StateGraph` — verified running with langgraph 1.2.16 (2026-10-22), with a parity test asserting the Lisbon itinerary matches the plain workflow exactly. It raises a clear ImportError when langgraph is not installed rather than pretending, and the parity test skips in that case.

## Grounding design

A `Claim` is `(text, record_ids)`. The builder creates claims only from the provider bundle it actually selected, and populates `itinerary.citations` from the same ids. `check_grounding` fails if a claim has no ids, or an id not in the gathered bundles' id set. The workflow surfaces that as an error — an ungrounded itinerary is not a successful result. This is what stops a future LLM explainer from inventing a price: its claims would have no resolvable ids.

## Provider design & failure handling

`TravelProvider` implementations return labeled records or raise `ProviderError`. Three cases, three structured outcomes — never invented data:
1. **Provider raises** → `ProviderUnavailable(reason=<error>)`.
2. **Provider returns nothing / unknown destination** → `ProviderUnavailable(reason="provider returned no options")`.
3. **Options exist but none satisfy hard constraints** → `ProviderUnavailable(reason="no destination satisfies hard constraints…")` with per-destination warnings preserved.

Timeouts/retries belong in future live adapters. Caching is built (below) and applies to fixture and live adapters alike through the same provider interface.

## Data & provenance

Every provider record carries `source` and `provenance`. Fixture data is `fixture`/`fixture` end-to-end, including in API responses and the web UI. A live adapter must set its real source name; mixing provenances in one itinerary is not currently supported.

## Persistence (built, SQLite-tested)

`myles/store.py` defines one interface, `TravelStore` (`save/load_preferences`, `save_itinerary`/`save_result`, `list_itineraries`). `SQLiteStore` (stdlib sqlite3) is the tested implementation: preferences upsert by user id, itinerary history appends and is listed newest-first, unknown users return `None`/`[]`. A new store instance on the same file sees prior data — that reopen behaviour is what the tests assert, and it is how "context preserved across interactions/restarts" is proven offline. `run_workflow(..., store=, user_id=)` records each plan through this interface. The Postgres adapter (`store_postgres.py` + `migrations/001_postgres.sql`) is an unverified skeleton with the same interface and payload shapes — no Postgres server exists in this environment, so it is labelled as such rather than claimed.

## Provider cache (built, in-memory + SQLite tested; Redis unverified)

`myles/cache.py` defines `ProviderCache` (`get`/`set` with TTL, hit/miss counters). Bundles are keyed by `(provider, origin, destination)` and serialised to JSON via their `to_dict()` shapes, then rebuilt into real dataclasses on read. The `gather_options` node consults the cache before calling `provider.search()` and populates it on a miss; the outcome is recorded on the result and in the run log (`cache_hit`, `cache_hits`, `cache_misses`, `cache_backend`). Provider errors are never cached, so an outage retries fresh. TTL expiry (including TTL=0) forces a refetch. Disabling — `cache_enabled=False`, `MYLES_CACHE_ENABLED=0`, or `NullCache` — is behaviour-identical apart from the provider being called every run; with no cache argument and no env opt-in, the old no-cache behaviour is preserved. Crucially, the cache replaces only the provider call: cached bundles still flow through constraint validation, building, and `verify_grounding`, so a fabricated claim fails grounding on a cache-hit run just as on a fresh run (tested). `RedisCache` implements the same interface behind a guarded `redis` import and is **unverified** — no Redis server exists in this environment. `CachedProvider` offers the same caching behind the provider interface for direct use, and `CountingProvider` is the test/eval instrument that proves call counts.

## Observability (built, JSON run logs + span-shaped tracing)

`myles/observability.py`: each workflow run builds one JSON run-log record — nodes visited, provider used, constraint result, latency ms, grounding outcome, cache hit/miss — attached to the result as `run_log` and optionally pushed to a log sink. It also emits **span-shaped** records: one root `workflow_run` span plus one child span per node (6 children), all sharing one `trace_id` (32 hex), each with `span_id` (16 hex), `parent_span_id`, start/end Unix-nanos, `duration_ms`, attributes (provider, cache hit, constraint result, plus node-specific attributes) and `status: {code: OK|ERROR}` — the node that newly produced an error/unavailability is marked ERROR, as is the root on a failed run. The plain workflow records real per-node timing; the LangGraph path synthesises spans from its trace (durations 0, status derived from outcome). This shape needs no OTEL SDK. When `opentelemetry-sdk` is installed (verified: 1.45.1 installs in this sandbox), `export_spans_with_otel()` re-emits the records as real OTEL spans through a `TracerProvider` + in-memory exporter, preserving parent/child contexts, and `run_workflow(otel_export=True)` / `MYLES_OTEL_EXPORT=1` enables that per run. No OTLP collector export is claimed. Remaining production step: LangSmith evaluation export. docker-compose.yml declares Postgres/Redis so the local infra shape is visible.
