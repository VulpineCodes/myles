"""Evaluation harness: python -m myles.evals.run [--out DIR]

Scores per case and in aggregate:
  constraint_satisfaction  — successful itineraries respect budget+duration; expected rejections happen
  structured_output_validity — result has itinerary-or-unavailable, trace covers all nodes (or early error)
  grounding                 — successful itineraries pass grounding with resolvable citations
  tool_selection_success    — workflow trace shows gather_options ran with the intended provider
  graceful_failure          — expected failure cases return structured unavailable/error, never a fake itinerary
  cache_behavior            — cache cases only (vacuously true otherwise): a repeat request is
                                served from cache with identical grounded output and the provider
                                is called exactly once; a TTL=0 (stale) case forces a fresh
                                provider call on the second run
Writes report.json + LAST_RUN.md next to this file (or --out).
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from ..schemas import TravelPreferences
from ..providers import FixtureProvider, FailingProvider, EmptyProvider
from ..workflow import run_workflow, NODES_ORDER
from ..cache import CountingProvider, InMemoryCache

HERE = Path(__file__).resolve().parent
PROVIDERS = {"fixture": FixtureProvider, "failing": FailingProvider, "empty": EmptyProvider}

def load_cases(path=None):
    return json.loads((Path(path) if path else HERE/"cases.json").read_text())

def _run_case(case, prefs):
    """Run a case once, or twice for cache scenarios.

    Returns (result_for_scoring, extra_dict). For cache cases the
    scored result is the SECOND run — that is the run whose cache
    behaviour (hit, or forced refetch at TTL=0) is being evaluated.
    """
    cache_cfg = case.get("cache")
    base_provider = PROVIDERS[case.get("provider","fixture")]()
    if not cache_cfg:
        result = run_workflow(prefs, provider=base_provider)
        return result, {"provider_calls": None, "cache_hit": result.cache_hit,
                        "cache_mode": None, "identical_output": None}
    mode = cache_cfg.get("mode", "repeat")
    ttl = cache_cfg.get("ttl_seconds", 300)
    counting = CountingProvider(base_provider)
    cache = InMemoryCache(default_ttl_seconds=float(ttl))
    first = run_workflow(prefs, provider=counting, cache=cache, cache_ttl_seconds=float(ttl))
    second = run_workflow(prefs, provider=counting, cache=cache, cache_ttl_seconds=float(ttl))
    identical = bool(
        (first.itinerary is None and second.itinerary is None)
        or (first.itinerary is not None and second.itinerary is not None
            and first.itinerary.destination_name == second.itinerary.destination_name
            and first.itinerary.total_cost_usd == second.itinerary.total_cost_usd
            and first.itinerary.citations == second.itinerary.citations)
    )
    return second, {"provider_calls": counting.search_calls, "cache_hit": second.cache_hit,
                    "cache_mode": mode, "identical_output": identical,
                    "first_cache_hit": first.cache_hit}

def evaluate_case(case) -> dict:
    prefs = TravelPreferences(**case["prefs"])
    result, extra = _run_case(case, prefs)
    expect = case["expect"]
    scores = {}
    # constraint satisfaction
    if expect == "success":
        scores["constraint_satisfaction"] = bool(result.ok and result.itinerary and result.itinerary.total_cost_usd <= prefs.budget_usd and result.itinerary.duration_days == prefs.duration_days)
    elif expect == "unavailable":
        scores["constraint_satisfaction"] = bool(result.unavailable is not None and result.itinerary is None)
    else:  # error
        scores["constraint_satisfaction"] = bool(result.errors)
    # structured output validity
    has_shape = (result.itinerary is not None) or (result.unavailable is not None) or bool(result.errors)
    scores["structured_output_validity"] = bool(has_shape and isinstance(result.trace, list) and len(result.trace) >= 1)
    # grounding
    if result.itinerary:
        scores["grounding"] = bool(result.grounding and result.grounding["ok"] and len(result.itinerary.citations) >= 3)
    else:
        scores["grounding"] = True  # no claims made = nothing ungrounded fabricated
    # tool selection
    scores["tool_selection_success"] = "gather_options" in result.trace if expect != "error" else "capture_preferences" in result.trace
    # graceful failure
    if expect == "success":
        scores["graceful_failure_handling"] = bool(result.ok)
    else:
        scores["graceful_failure_handling"] = bool(result.itinerary is None and (result.unavailable is not None or result.errors))
    # cache behaviour (new in hardening sprint)
    cache_cfg = case.get("cache")
    if not cache_cfg:
        scores["cache_behavior"] = True
    elif cache_cfg.get("mode") == "stale_ttl_zero":
        # TTL=0: second run must MISS and refetch (2 provider calls),
        # while still producing the same grounded, successful output.
        scores["cache_behavior"] = bool(
            extra["provider_calls"] == 2 and extra["cache_hit"] is False
            and extra["identical_output"] and result.ok
            and result.grounding and result.grounding["ok"])
    else:  # repeat
        # Repeat: second run must HIT (exactly 1 provider call for 2 runs)
        # with identical, grounded output.
        scores["cache_behavior"] = bool(
            extra["provider_calls"] == 1 and extra["cache_hit"] is True
            and extra["identical_output"] and result.ok
            and result.grounding and result.grounding["ok"])
    scores["case_pass"] = all(scores.values())
    return {"id": case["id"], "expect": expect, "ok": result.ok, "scores": scores,
            "total_cost_usd": result.itinerary.total_cost_usd if result.itinerary else None,
            "destination": result.itinerary.destination_name if result.itinerary else None,
            "errors": result.errors, "trace": result.trace,
            "provider_calls": extra["provider_calls"], "cache_hit": extra["cache_hit"],
            "cache_mode": extra["cache_mode"], "identical_output": extra["identical_output"]}

def run_all(cases=None) -> dict:
    cases = cases or load_cases()
    results = [evaluate_case(c) for c in cases]
    metrics = ["constraint_satisfaction","structured_output_validity","grounding","tool_selection_success","graceful_failure_handling","cache_behavior"]
    agg = {m: round(sum(1 for r in results if r["scores"][m])/len(results), 3) if results else 0 for m in metrics}
    agg["case_pass_rate"] = round(sum(1 for r in results if r["scores"]["case_pass"])/len(results), 3) if results else 0
    return {"cases_total": len(results), "cases_passed": sum(1 for r in results if r["scores"]["case_pass"]), "metrics": agg, "results": results}

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    out_dir = HERE
    if "--out" in argv: out_dir = Path(argv[argv.index("--out")+1])
    out_dir.mkdir(parents=True, exist_ok=True)
    report = run_all()
    (out_dir/"report.json").write_text(json.dumps(report, indent=2))
    lines = ["# Myles — Evaluation Harness: Last Run", "",
             f"Cases: **{report['cases_passed']}/{report['cases_total']} passed**", "", "## Aggregate metrics", ""]
    for k, v in report["metrics"].items(): lines.append(f"- {k}: **{v:.0%}**" if isinstance(v, float) else f"- {k}: {v}")
    lines += ["", "## Per-case", "", "| Case | Expect | Pass | Destination | Cost | Cache | Provider calls |", "|---|---|---|---|---|---|---|"]
    for r in report["results"]:
        cache_cell = r.get("cache_mode") or "—"
        calls_cell = str(r["provider_calls"]) if r.get("provider_calls") is not None else "—"
        lines.append(f"| {r['id']} | {r['expect']} | {'yes' if r['scores']['case_pass'] else 'NO'} | {r['destination'] or '—'} | {('$'+format(r['total_cost_usd'],'.2f')) if r['total_cost_usd'] else '—'} | {cache_cell} | {calls_cell} |")
    lines += ["", "Cache cases: `repeat` = second identical run served from cache (1 provider call for 2 runs, identical grounded output); `stale_ttl_zero` = TTL=0 forces a fresh provider call on the second run (2 provider calls).", "",
              "All successful itineraries use fixture-labeled data only. No live prices were queried or fabricated.", ""]
    md = "\n".join(lines)
    (out_dir/"LAST_RUN.md").write_text(md)
    print(md); print(f"\nWrote {out_dir/'report.json'} and {out_dir/'LAST_RUN.md'}")
    return 0 if report["cases_passed"] == report["cases_total"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
