# STATUS — Myles

Last verified: 2026-10-22 (offline sandbox: Python 3.12, Node 24, no Docker, no GitHub auth, no model/travel API keys, no Redis server)

## Verified results

- **pytest: 50 passed, 0 failed** (`python -m pytest -q`, venv with pytest/pydantic/langgraph/opentelemetry-sdk)
  - Foundation (15): test_validator.py 3, test_builder.py 3, test_grounding.py 3, test_provider_failure.py 4, test_evals.py 2 (now 3, see below)
  - MVP sprint (+14): test_store.py 7, test_observability.py 5, test_langgraph_parity.py 2
  - Hardening sprint (+21): test_cache.py 15, test_tracing.py 5, test_evals.py +1 (cache-case coverage + provider-call evidence)
- **Eval harness: 13/13 cases passed; all aggregate metrics 100%** — constraint_satisfaction, structured_output_validity, grounding, tool_selection_success, graceful_failure_handling, and the new cache_behavior. Full report: `myles/evals/LAST_RUN.md` + `myles/evals/report.json` (`python -m myles.evals.run`). The 3 new cache cases carry provider-call evidence in the report: `cache_repeat_lisbon` 1 call / 2 runs, `cache_repeat_denver` 1 call / 2 runs, `cache_stale_ttl_zero` 2 calls / 2 runs. No metric moved from 100% — the cache cases were added as a separate `cache_behavior` metric rather than diluting the original five, and all five originals remain 100% on the expanded 13-case set.
- **Provider cache: TESTED core.** `myles/cache.py` — in-memory and SQLite adapters pass: second identical workflow run hits cache and does not call the provider (CountingProvider: search_calls stays 1), miss populates, TTL expiry (fake clock) and TTL=0 force refetch, disabled cache (NullCache / `cache_enabled=False` / env) calls the provider every run with identical results ($855.00 Lisbon), provider errors are never cached, different destination = different key, SQLite cache survives a new instance. Grounding is never bypassed: a cache-hit run still traces `verify_grounding`, and a monkeypatched fabricated claim fails grounding on a cache-hit run. Run log and result record `cache_hit`/`cache_hits`/`cache_misses`/`cache_backend` per run. **RedisCache adapter is UNVERIFIED** — guarded import, same interface/serialisation, never run against a server (none exists here).
- **Span-shaped tracing: TESTED.** Every run emits 1 root span + 6 child spans (one per workflow node) under one `trace_id`, OTEL-shaped JSON (`trace_id`/`span_id`/`parent_span_id`/`name`/start/end nanos/`duration_ms`/`attributes`/`status`); gather span records `cache_hit`, every node span carries provider + constraint_result. Failure runs mark the failing span `status.code=ERROR` (gather_options for a provider outage, capture_preferences for invalid input) and the root ERROR. **OTEL SDK outcome: INSTALLED.** One bounded `pip install opentelemetry-sdk` succeeded (~7s, version 1.45.1, with opentelemetry-api 1.45.1); the optional exporter path (`export_spans_with_otel`, `otel_export=True`) re-emits the 7 spans as real OTEL spans via an in-memory exporter and is covered by a test that runs (not skips) when the SDK is present and skips cleanly when it is absent. No OTLP collector was used or claimed.
- **LangGraph: INSTALLED and RUNNING (verified 2026-10-22).** langgraph 1.2.16. `build_langgraph()` compiles a real StateGraph from workflow.py's node functions (now including the shared cached gather node); parity test still passes — Lisbon itinerary matches the plain workflow exactly ($855.00, same ids/citations/grounding/trace). Plain graph remains the dependency-free primary; parity test skips when langgraph is absent.
- **Frontend: TYPECHECK CLEAN (re-verified in hardening sprint).** `npx tsc --noEmit` exit 0 in `web/`; no `web/` changes were needed or made in this sprint. Earlier verification (2026-10-22): `npm install`, `npm run build` (Next.js 14.2.35) pass.
- **Persistence: SQLite is the tested path.** `myles/store.py` `SQLiteStore` (stdlib sqlite3) — preferences upsert/load by user id, itinerary history append/list (newest first). Reopen tests use a new instance + new connections on the same file, simulating restart. Workflow wiring: `run_workflow(..., store=store, user_id=...)` saves preferences + records each plan; a store failure is surfaced as a warning, not a fake planning failure.
- **Observability: structured JSON run logs + spans.** `myles/observability.py` — every result carries `run_log` {event, timestamp, nodes_visited, provider_used, constraint_result, latency_ms, ok, grounding_ok, destination, total_cost_usd, cache_*, trace_id, spans} plus `spans`/`trace_id` fields on the result itself; optional `log_sink` (list/callable/file, else stdlib logging as one JSON line).
- **FastAPI smoke test (foundation; re-verified 2026-10-22 in the docs claims audit via TestClient):** `GET /health` → `{status: ok, provider: fixture}`, `GET /destinations` → 4 fixture destinations, `POST /plan` Lisbon/$1800/4d → grounded itinerary $855.00, over-budget Kyoto/$200 → structured `provider_unavailable`.

- **Docs claims audit (2026-10-22):** every quantitative claim in README.md / ARCHITECTURE.md / this file was checked against a fresh test + eval run and installed package versions (pytest 50 with per-file counts, eval 13/13 at 100% on all six metrics, langgraph 1.2.16, opentelemetry-sdk 1.45.1, Next.js 14.2.35 in web/package-lock.json, Lisbon $855.00 in eval report + API smoke). No claim required correction; the audit added the README "Origins" section linking the original externship repo.

## Acceptance criteria — MVP

- [x] User request → structured, usable itinerary (deterministic builder, score breakdown + trade-offs)
- [x] Constraints respected and evidence exposed (citations = provider record ids, grounding-checked)
- [x] Evaluation harness runs reproducibly and produces a report (13/13, incl. 3 cache cases)
- [x] Important failure paths tested (provider failure, empty data, impossible constraints, ungrounded claim, invalid input)
- [x] Persistence: preferences + itinerary history preserved across restarts (SQLite, tested)
- [x] LangGraph workflow actually runs, with parity test vs the plain graph
- [x] Frontend installs, typechecks and builds
- [x] Structured run logging / trace record per workflow run
- [x] Provider-response cache with tested core (hit/miss/TTL/disabled/grounding, Redis adapter unverified)
- [x] Span-shaped per-node tracing; real-OTEL exporter path when the SDK is present
- [x] CI workflow defined (.github/workflows/ci.yml: pytest incl. langgraph + opentelemetry-sdk + eval harness + real frontend build) — not yet run on GitHub (no auth in sandbox)
- [x] Setup + architecture documentation (README.md, ARCHITECTURE.md)
- [ ] Deployed application verified — **blocked**: no deployment credentials / Docker in sandbox
- [ ] Live travel provider integration — **blocked**: no travel API keys; FixtureProvider only, clearly labeled
- [ ] LLM explainer — **blocked**: no model API key; deterministic explainer is default, LLM stub disabled without `MODEL_API_KEY`

## Honest limitations

- **No live data anywhere.** All flights/lodging/activities are fixture samples with stable ids. Nothing here is a real price or real availability.
- **Postgres adapter is a skeleton, UNVERIFIED.** `myles/store_postgres.py` implements the `TravelStore` interface shape but every method raises NotImplementedError with SQL sketches; DDL in `myles/migrations/001_postgres.sql` has never been executed (no Postgres server here). SQLite is the only tested persistence path.
- **Redis cache adapter is UNVERIFIED.** `RedisCache` in `myles/cache.py` has never run against a Redis server (none exists here); the tested cache backends are in-memory and SQLite.
- **OTEL export is in-memory only.** The SDK path proves the span shape maps onto real OTEL spans; no OTLP collector, LangSmith export, or remote tracing backend was run.
- **Cache is opt-in by default.** Without a `cache=` argument, `cache_enabled=True`, or `MYLES_CACHE_ENABLED=1`, runs keep the original no-cache behaviour — a shared cache instance must be passed for cross-run hits, which is exactly what the tests/evals do.
- **LLM explainer is a stub** (disabled, requires `MODEL_API_KEY`). Default explanations are deterministic templates.
- **Frontend is build-verified, not e2e-verified**: no Playwright run against a live API in this sandbox, and the app is not deployed.

## Architecture decisions

- Core uses dataclasses + explicit validation (stdlib-only, offline-testable); Pydantic/FastAPI live only at the API boundary.
- Hard constraints reject; soft constraints (interest match) warn. Builder never silently relaxes budget.
- Fixture-first: provenance is a field on every record, not a README disclaimer.
- Persistence behind one interface (`TravelStore`): SQLite proves the semantics locally; Postgres swaps in without caller changes when a server exists.
- Cache behind one interface (`ProviderCache`): in-memory/SQLite prove the semantics locally; Redis swaps in without caller changes when a server exists. Cache sits *before* the provider call and *after* nothing else — validation/building/grounding always run.
- Observability without a collector: a JSON run-log + OTEL-shaped spans on every result, sink-pluggable, with an optional real-SDK exporter that needs no collector.

## Next tasks

1. Add a real provider adapter behind `TravelProvider` when a key is available; keep fixture as the eval baseline.
2. Implement `PostgresStore` against a real server and parametrize tests/test_store.py over both adapters; verify `RedisCache` against a real Redis.
3. Wire the LLM explainer (ground-check its output) when `MODEL_API_KEY` is available.
4. Add an OTLP exporter configuration + a Playwright smoke test for web/ against the API.
5. Deploy API + web where credentials permit and verify the deployed `/plan` flow.
