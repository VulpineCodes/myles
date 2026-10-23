from myles.schemas import TravelPreferences, Itinerary
from myles.providers import FixtureProvider
from myles.validator import validate_itinerary
from myles.builder import build_for_bundle

def test_over_budget_itinerary_rejected():
    prefs = TravelPreferences(origin="Nashville", destination="Lisbon", budget_usd=100, duration_days=4)
    itin = Itinerary(destination_id="dest_lisbon", destination_name="Lisbon", flight_id="flt_lisbon_1", lodging_id="lod_lisbon_1", total_cost_usd=999.0, duration_days=4)
    v = validate_itinerary(prefs, itin)
    assert not v.ok and any("budget" in x for x in v.hard_violations)

def test_wrong_duration_rejected():
    prefs = TravelPreferences(origin="Nashville", budget_usd=5000, duration_days=4)
    itin = Itinerary(destination_id="x", destination_name="X", flight_id=None, lodging_id=None, total_cost_usd=100, duration_days=9)
    assert not validate_itinerary(prefs, itin).ok

def test_max_lodging_enforced():
    provider = FixtureProvider(); bundle = provider.get_bundle("dest_lisbon", "Nashville")
    prefs = TravelPreferences(origin="Nashville", budget_usd=5000, duration_days=4, max_lodging_per_night_usd=60)
    itin = Itinerary(destination_id="dest_lisbon", destination_name="Lisbon", flight_id="flt_lisbon_1", lodging_id="lod_lisbon_1", total_cost_usd=500, duration_days=4)
    v = validate_itinerary(prefs, itin, bundle)
    assert not v.ok  # $95/night > $60 cap
