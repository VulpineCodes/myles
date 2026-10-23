"""Provider cache tests — hit avoids provider call, TTL, disabled,
grounding is never bypassed. CountingProvider is the proof instrument:
provider call counts are asserted, not inferred from timing."""
import time

import pytest

from myles.cache import (
    CountingProvider, InMemoryCache, NullCache, SQLiteCache,
    CachedProvider, get_default_cache, make_cache_key,
)
from myles.providers import FixtureProvider, FailingProvider
from myles.schemas import TravelPreferences
from myles.workflow import run_workflow
import myles.workflow as workflow_mod

PREFS = TravelPreferences(origin="Nashville", destination="Lisbon", budget_usd=1800,
                          duration_days=4, interests=["food", "history"])


# --- interface / key -------------------------------------------------------

def test_cache_key_is_provider_origin_destination():
    assert make_cache_key("fixture", "Nashville", "Lisbon") == "fixture:nashville:lisbon"
    assert make_cache_key("fixture", "Nashville", None) == "fixture:nashville:"


def test_inmemory_get_set_and_stats():
    cache = InMemoryCache(default_ttl_seconds=60)
    provider = FixtureProvider()
    bundles = provider.search("Nashville", "Lisbon", ["food"])
    key = make_cache_key("fixture", "Nashville", "Lisbon")
    assert cache.get(key) is None and cache.misses == 1
    cache.set(key, bundles)
    got = cache.get(key)
    assert got is not None and cache.hits == 1
    assert [b.destination.id for b in got] == [b.destination.id for b in bundles]
    assert got[0].all_ids() == bundles[0].all_ids()


def test_sqlite_cache_survives_new_instance(tmp_path):
    path = tmp_path / "cache.db"
    provider = FixtureProvider()
    bundles = provider.search("Nashville", "Lisbon", ["food"])
    key = make_cache_key("fixture", "Nashville", "Lisbon")
    SQLiteCache(path).set(key, bundles)
    got = SQLiteCache(path).get(key)  # new instance, new connection
    assert got is not None
    assert got[0].destination.id == "dest_lisbon"
    assert got[0].flights[0].id == bundles[0].flights[0].id


# --- workflow wiring: hit avoids provider call ------------------------------

def test_second_identical_run_hits_cache_and_skips_provider():
    counting = CountingProvider(FixtureProvider())
    cache = InMemoryCache(default_ttl_seconds=300)
    r1 = run_workflow(PREFS, provider=counting, cache=cache)
    assert r1.ok and counting.search_calls == 1
    assert r1.cache_hit is False and r1.cache_misses == 1 and r1.cache_enabled
    assert r1.run_log["cache_hit"] is False

    r2 = run_workflow(PREFS, provider=counting, cache=cache)
    # THE proof: provider was NOT called again.
    assert counting.search_calls == 1, f"expected 1 provider call, got {counting.search_calls}"
    assert r2.cache_hit is True and r2.cache_hits == 1
    assert r2.run_log["cache_hit"] is True and r2.run_log["cache_hits"] == 1
    # Identical grounded output from cache.
    assert r2.itinerary.total_cost_usd == r1.itinerary.total_cost_usd == 855.0
    assert r2.itinerary.citations == r1.itinerary.citations
    assert r2.grounding and r2.grounding["ok"]


def test_miss_populates_cache_sqlite(tmp_path):
    counting = CountingProvider(FixtureProvider())
    cache = SQLiteCache(tmp_path / "c.db", default_ttl_seconds=300)
    run_workflow(PREFS, provider=counting, cache=cache)
    assert counting.search_calls == 1 and cache.hits == 0 and cache.misses == 1
    run_workflow(PREFS, provider=counting, cache=cache)
    assert counting.search_calls == 1 and cache.hits == 1


def test_different_destination_is_a_different_key():
    counting = CountingProvider(FixtureProvider())
    cache = InMemoryCache(default_ttl_seconds=300)
    run_workflow(PREFS, provider=counting, cache=cache)
    run_workflow(TravelPreferences(origin="Nashville", destination="Denver", budget_usd=1800,
                                   duration_days=4, interests=["nature"]),
                 provider=counting, cache=cache)
    assert counting.search_calls == 2


def test_cached_provider_wrapper_also_skips_inner():
    counting = CountingProvider(FixtureProvider())
    cached = CachedProvider(counting, InMemoryCache(default_ttl_seconds=300))
    cached.search("Nashville", "Lisbon", ["food"])
    cached.search("Nashville", "Lisbon", ["food"])
    assert counting.search_calls == 1 and cached.hits == 1 and cached.misses == 1


# --- TTL expiry ---------------------------------------------------------------

def test_ttl_expiry_forces_refetch_with_fake_clock():
    now = [1000.0]
    cache = InMemoryCache(default_ttl_seconds=10, clock=lambda: now[0])
    counting = CountingProvider(FixtureProvider())
    run_workflow(PREFS, provider=counting, cache=cache)
    run_workflow(PREFS, provider=counting, cache=cache)
    assert counting.search_calls == 1
    now[0] += 11  # past TTL
    r = run_workflow(PREFS, provider=counting, cache=cache)
    assert counting.search_calls == 2 and r.cache_hit is False


def test_ttl_zero_forces_fresh_provider_data():
    counting = CountingProvider(FixtureProvider())
    cache = InMemoryCache(default_ttl_seconds=0)
    run_workflow(PREFS, provider=counting, cache=cache, cache_ttl_seconds=0)
    run_workflow(PREFS, provider=counting, cache=cache, cache_ttl_seconds=0)
    assert counting.search_calls == 2


# --- disabled cache -----------------------------------------------------------

def test_disabled_cache_via_null_cache_behaves_identically():
    counting = CountingProvider(FixtureProvider())
    r1 = run_workflow(PREFS, provider=counting, cache=NullCache())
    r2 = run_workflow(PREFS, provider=counting, cache=NullCache())
    assert counting.search_calls == 2  # provider every time
    assert r1.ok and r2.ok and not r1.cache_enabled
    assert r1.itinerary.total_cost_usd == r2.itinerary.total_cost_usd == 855.0


def test_disabled_cache_via_flag_and_env(monkeypatch):
    counting = CountingProvider(FixtureProvider())
    run_workflow(PREFS, provider=counting, cache_enabled=False)
    run_workflow(PREFS, provider=counting, cache_enabled=False)
    assert counting.search_calls == 2
    monkeypatch.setenv("MYLES_CACHE_ENABLED", "0")
    assert isinstance(get_default_cache(), NullCache)
    monkeypatch.setenv("MYLES_CACHE_ENABLED", "1")
    assert isinstance(get_default_cache(), InMemoryCache)


def test_no_cache_by_default_preserves_old_behaviour():
    counting = CountingProvider(FixtureProvider())
    run_workflow(PREFS, provider=counting)
    run_workflow(PREFS, provider=counting)
    assert counting.search_calls == 2


def test_provider_errors_are_not_cached():
    counting = CountingProvider(FailingProvider())
    cache = InMemoryCache(default_ttl_seconds=300)
    r1 = run_workflow(PREFS, provider=counting, cache=cache)
    r2 = run_workflow(PREFS, provider=counting, cache=cache)
    assert not r1.ok and not r2.ok
    assert counting.search_calls == 2  # outage retries fresh, not cached


# --- grounding is never bypassed ----------------------------------------------

def test_cache_hit_run_still_runs_grounding():
    cache = InMemoryCache(default_ttl_seconds=300)
    counting = CountingProvider(FixtureProvider())
    run_workflow(PREFS, provider=counting, cache=cache)
    r2 = run_workflow(PREFS, provider=counting, cache=cache)
    assert r2.cache_hit is True
    assert "verify_grounding" in r2.trace
    assert r2.grounding is not None and r2.grounding["ok"]


def test_fabricated_claim_still_fails_grounding_on_cache_hit(monkeypatch):
    """Poison the builder's output on a cache-hit run: grounding must catch it."""
    from myles.schemas import Claim
    cache = InMemoryCache(default_ttl_seconds=300)
    counting = CountingProvider(FixtureProvider())
    run_workflow(PREFS, provider=counting, cache=cache)
    assert counting.search_calls == 1

    real_build = workflow_mod.build_itinerary

    def poisoned(prefs, bundles):
        itin = real_build(prefs, bundles)
        if itin is not None:
            itin.claims.append(Claim("Fabricated flight costs $1.", ["flt_does_not_exist"]))
            itin.citations.append("flt_does_not_exist")
        return itin

    monkeypatch.setattr(workflow_mod, "build_itinerary", poisoned)
    r = run_workflow(PREFS, provider=counting, cache=cache)
    assert r.cache_hit is True and counting.search_calls == 1  # served from cache
    assert not r.ok and r.grounding is not None and not r.grounding["ok"]
    assert any("ungrounded" in e for e in r.errors)
