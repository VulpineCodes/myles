from myles.evals.run import run_all, load_cases

def test_eval_cases_at_least_eight_and_cover_required_kinds():
    cases = load_cases()
    assert len(cases) >= 8
    ids = {c["id"] for c in cases}
    assert "provider_failure" in ids and "over_budget_kyoto" in ids and "impossible_constraints" in ids

def test_eval_cases_include_three_cache_cases():
    cases = load_cases()
    cache_ids = {c["id"] for c in cases if c.get("cache")}
    assert cache_ids == {"cache_repeat_lisbon", "cache_repeat_denver", "cache_stale_ttl_zero"}
    modes = {c["id"]: c["cache"]["mode"] for c in cases if c.get("cache")}
    assert modes["cache_stale_ttl_zero"] == "stale_ttl_zero"
    assert modes["cache_repeat_lisbon"] == "repeat"

def test_eval_harness_runs_and_scores():
    report = run_all()
    assert report["cases_total"] >= 8
    for m in ["constraint_satisfaction","structured_output_validity","grounding","tool_selection_success","graceful_failure_handling","cache_behavior"]:
        assert m in report["metrics"] and report["metrics"][m] >= 0.9, report["metrics"]
    # Cache evidence must be in the per-case results, not just the score.
    by_id = {r["id"]: r for r in report["results"]}
    assert by_id["cache_repeat_lisbon"]["provider_calls"] == 1
    assert by_id["cache_repeat_lisbon"]["cache_hit"] is True
    assert by_id["cache_repeat_lisbon"]["identical_output"] is True
    assert by_id["cache_stale_ttl_zero"]["provider_calls"] == 2
    assert by_id["cache_stale_ttl_zero"]["cache_hit"] is False
