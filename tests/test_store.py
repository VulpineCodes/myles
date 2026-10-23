"""Persistence tests — SQLiteStore is the tested adapter.

Proves planning context survives a restart: a *new* SQLiteStore on the
same file (new sqlite3 connections throughout) sees data written by
the previous instance.
"""
from myles.schemas import TravelPreferences
from myles.store import SQLiteStore
from myles.workflow import run_workflow

PREFS = TravelPreferences(origin="Nashville", destination="Lisbon", budget_usd=1800,
                          duration_days=4, interests=["food", "history"])


def test_preferences_survive_store_reopen(tmp_path):
    db = tmp_path / "myles.db"
    SQLiteStore(db).save_preferences("franklin", PREFS)
    # New instance, new connections, same file == simulated restart.
    loaded = SQLiteStore(db).load_preferences("franklin")
    assert loaded is not None
    assert loaded.to_dict() == PREFS.to_dict()


def test_preferences_upsert_overwrites(tmp_path):
    store = SQLiteStore(tmp_path / "m.db")
    store.save_preferences("u1", PREFS)
    updated = TravelPreferences(origin="New York", destination="Denver", budget_usd=900, duration_days=2, interests=["nature"])
    store.save_preferences("u1", updated)
    assert store.load_preferences("u1").to_dict() == updated.to_dict()


def test_unknown_user_returns_empty_not_error(tmp_path):
    store = SQLiteStore(tmp_path / "m.db")
    assert store.load_preferences("nobody") is None
    assert store.list_itineraries("nobody") == []
    assert store.list_history("nobody") == []


def test_itinerary_history_accumulates(tmp_path):
    store = SQLiteStore(tmp_path / "m.db")
    r1 = run_workflow(PREFS, store=store, user_id="franklin")
    assert r1.ok
    history = store.list_itineraries("franklin")
    assert len(history) == 1
    assert history[0]["itinerary"]["destination_name"] == "Lisbon"
    assert history[0]["itinerary"]["total_cost_usd"] == r1.itinerary.total_cost_usd

    prefs2 = TravelPreferences(origin="Nashville", destination="Denver", budget_usd=900,
                               duration_days=2, interests=["nature"])
    r2 = run_workflow(prefs2, store=store, user_id="franklin")
    assert r2.ok
    history = store.list_itineraries("franklin")
    assert len(history) == 2
    # Newest first; both plans are retained, neither overwrote the other.
    assert history[0]["itinerary"]["destination_name"] == "Denver"
    assert history[1]["itinerary"]["destination_name"] == "Lisbon"
    # Preferences were also updated to the most recent run's.
    assert store.load_preferences("franklin").destination == "Denver"


def test_history_is_per_user(tmp_path):
    store = SQLiteStore(tmp_path / "m.db")
    run_workflow(PREFS, store=store, user_id="alice")
    assert len(store.list_itineraries("alice")) == 1
    assert store.list_itineraries("bob") == []


def test_history_survives_reopen(tmp_path):
    db = tmp_path / "m.db"
    run_workflow(PREFS, store=SQLiteStore(db), user_id="franklin")
    reopened = SQLiteStore(db)
    assert len(reopened.list_itineraries("franklin")) == 1
    assert reopened.load_preferences("franklin").destination == "Lisbon"


def test_save_itinerary_direct(tmp_path):
    store = SQLiteStore(tmp_path / "m.db")
    result = run_workflow(PREFS)
    row_id = store.save_itinerary("u9", result.itinerary, prefs=PREFS, ok=result.ok)
    assert isinstance(row_id, int) and row_id >= 1
    (entry,) = store.list_itineraries("u9")
    assert entry["ok"] is True
    assert entry["destination_name"] == "Lisbon"
    assert entry["prefs"]["origin"] == "Nashville"
