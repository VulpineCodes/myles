# Myles — Travel Intelligence Assistant

Myles started during my FactSet externship as a travel assistant idea. This is the independent rebuild: not a chatbot that sounds confident, but a planner that has to show its work — every price it quotes traces to a provider record, every plan has to survive a budget check, and when it has nothing verified to say, it says so.

## Origins

This project re-architects the original Myles, built during a FactSet externship in 2025 and still public at **[VulpineCodes/myles-travel-buddy-](https://github.com/VulpineCodes/myles-travel-buddy-)**. The original was a Streamlit-style app (`app.py` plus helper modules for flights, country data, Unsplash and Reddit) offering destination information, flight search, and preference-aware recommendations, including dietary restrictions. It was an externship exploration, not a production system — and it is preserved untouched; nothing in this repo modifies it.

**What carried over:** the name, and the core concept — a travel assistant called Myles that shapes recommendations around a traveller's preferences and constraints instead of returning generic lists.

**What is new here:** essentially the entire engineering approach. A deterministic planner with an explicit scoring function instead of free-form chat answers; hard-constraint validation that rejects over-budget plans; a grounding checker so every quoted price cites a real provider record; a reproducible evaluation harness; the workflow implemented twice (a dependency-free graph and LangGraph, with a parity test); SQLite persistence for preferences and itinerary history; a provider-response cache; and span-shaped tracing. The stack changed too: FastAPI + Next.js here, versus the original's single-app Streamlit style.

## The rule that shapes everything

**Myles never fabricates.** No invented flight prices, no invented hotel availability, no citations to sources that don't exist. If a provider fails or returns nothing, you get a structured `provider_unavailable` result — not a plausible-sounding itinerary.

## What works today (offline, no keys)

- **Deterministic planner** (`myles/builder.py`): picks flight + lodging + activities by an explicit score — `0.45·cost + 0.35·interest match + 0.20·rating` — and returns the score breakdown and trade-offs with the plan.
- **Hard-constraint validation** (`myles/validator.py`): over-budget or wrong-duration itineraries are rejected, not warned about.
- **Grounding checker** (`myles/grounding.py`): every claim in an itinerary must cite a real provider record id. Ungrounded claims fail the workflow.
- **Explicit workflow graph** (`myles/workflow.py`): `capture_preferences → gather_options → validate_constraints → build_itinerary → explain_tradeoffs → verify_grounding`, with the node trace recorded on every result.
- **Evaluation harness** (`myles/evals/`): 13 cases — normal trips, an over-budget request, impossible constraints, a simulated provider outage, missing data, leap-day and single-day edges, plus 3 cache cases (2× repeat-served-from-cache, 1× stale TTL=0). Run it, don't trust my summary: `python -m myles.evals.run` (latest output in `myles/evals/LAST_RUN.md`).
- **Fixture provider**: four destinations (Lisbon, Mexico City, Kyoto, Denver) with sample flights/lodging/activities. Every record says `provenance: fixture`. It is sample data for development and evaluation — **not** live prices or availability.
- **Persistence** (`myles/store.py`): `SQLiteStore` (stdlib `sqlite3`, zero extra deps) saves preferences per user and appends every plan to that user's itinerary history. Data survives a new store instance / new connections on the same file — context really is preserved across restarts. Unknown users get `None` / `[]`, never an error. `run_workflow(prefs, store=store, user_id="…")` wires it in. The future Postgres adapter is a skeleton with the same interface (`myles/store_postgres.py` + `myles/migrations/001_postgres.sql`), **labelled unverified** — no Postgres server exists here.
- **LangGraph** (`myles/workflow_langgraph.py`): verified running 2026-10-22 — `pip install langgraph` (1.2.16) succeeded on retry, the compiled `StateGraph` uses the identical node functions, and a parity test asserts its Lisbon itinerary matches the plain workflow exactly (cost $855.00, same record ids/citations/grounding/trace). The plain graph remains the dependency-free primary; the parity test skips when langgraph is absent.
- **Structured run logging** (`myles/observability.py`): every run attaches a JSON `run_log` to its result — nodes visited, provider used, constraint result, latency ms, grounding outcome, cache hit/miss — and can push it to a caller-supplied log sink (list / callable / file).
- **Provider-response cache** (`myles/cache.py`): `ProviderCache` interface (get/set with TTL) with tested in-memory + SQLite implementations. Key is `(provider, origin, destination)`; a second identical run hits the cache and does **not** call the provider (proven by a counting-provider test: 1 search call for 2 runs), TTL expiry / TTL=0 forces a refetch, and disabling (`cache_enabled=False`, `MYLES_CACHE_ENABLED=0`, or `NullCache`) is behaviour-identical, just slower. Provider errors are never cached. The cache only replaces the `gather_options` provider call — cached bundles still go through constraint validation and grounding (a fabricated-claim test fails grounding on a cache-hit run). A `RedisCache` adapter implements the same interface behind a guarded import and is **labelled unverified** — no Redis server exists here. Also usable standalone as `CachedProvider` / `CountingProvider`.
- **Span-shaped tracing** (`myles/observability.py`): every run also emits OTEL-shaped span records — one root `workflow_run` span + 6 child spans (one per node) sharing one `trace_id`, with `span_id`/`parent_span_id`, start/end nanos, duration, attributes (provider, cache hit, constraint result) and `status.code` OK/ERROR (the failing node is ERROR on failure runs). No OTEL SDK is required for the JSON shape. When `opentelemetry-sdk` is present (verified installable here: 1.45.1), `export_spans_with_otel()` / `run_workflow(..., otel_export=True)` additionally re-emits them as real OTEL spans via an in-memory exporter (7 spans) — no OTLP collector is claimed.
- **Frontend** (`web/`): verified 2026-10-22 — `npm install`, `npx tsc --noEmit` and `npm run build` (Next.js 14.2.35) all pass; `/` prerenders statically.

## What needs keys / is not done yet

- **Live travel providers**: none integrated. There are no travel API keys in this environment, and the provider interface (`myles/providers.py`) is where a real adapter belongs.
- **LLM explanations**: isolated behind an `Explainer` interface. The default is deterministic and template-based. `LLMExplainer` is a disabled stub that requires `MODEL_API_KEY` — see ARCHITECTURE.md.
- **Postgres/Redis in production**: SQLite is the tested persistence path; Postgres is an unverified skeleton (above) and the Redis cache adapter is unverified (no Redis server here) — the tested cache backends are in-memory and SQLite.
- **Deployment**: not deployed — no deployment credentials / Docker in this environment.

## Run it

```bash
pip install pytest pydantic          # core + tests need only these
python -m pytest -q                  # test suite (50 tests)
python -m myles.evals.run            # evaluation harness -> report.json + LAST_RUN.md
pip install langgraph                # optional: enables the LangGraph parity tests
pip install opentelemetry-sdk        # optional: enables the real-OTEL exporter test/path

pip install -r requirements.txt      # full API stack
uvicorn myles.api.app:app --reload   # POST /plan, GET /destinations, GET /health
docker compose up                    # postgres + redis + api + web (when Docker is available)

cd web && npm install && npx tsc --noEmit && npm run build   # frontend (verified)
```

Persist a plan and read it back after a restart:

```python
from myles.schemas import TravelPreferences
from myles.store import SQLiteStore
from myles.workflow import run_workflow
store = SQLiteStore("myles.db")
run_workflow(TravelPreferences(origin="Nashville", destination="Lisbon", budget_usd=1800),
             store=store, user_id="franklin")
SQLiteStore("myles.db").list_itineraries("franklin")   # -> the plan above, in a new process too
SQLiteStore("myles.db").load_preferences("franklin")   # -> the saved preferences
```

Frontend in `web/` (Next.js): a trip request form and an itinerary view that renders trade-offs and citations alongside the plan.

## Layout

```
myles/            core package (schemas, providers, validator, builder, grounding, explainer,
                  workflow, store, store_postgres, observability, cache, workflow_langgraph)
myles/api/        FastAPI boundary
myles/evals/      cases.json (13 cases incl. 3 cache cases), runner, LAST_RUN.md
myles/migrations/ Postgres DDL (001_postgres.sql — unverified skeleton)
tests/            pytest suite (validator, builder, grounding, provider failure, evals,
                  store, observability, cache, tracing, langgraph parity)
web/              Next.js frontend (install / typecheck / build verified)
ARCHITECTURE.md   deterministic vs model reasoning, grounding, failure handling
STATUS.md         verified results and honest limitations
```
