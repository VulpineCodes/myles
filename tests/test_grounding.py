from myles.schemas import Claim, Itinerary
from myles.grounding import check_grounding, check_claims
from myles.providers import FixtureProvider
from myles.schemas import TravelPreferences
from myles.workflow import run_workflow

def test_grounding_catches_claim_with_no_citation():
    itin = Itinerary(destination_id="dest_lisbon", destination_name="Lisbon", flight_id=None, lodging_id=None,
                     claims=[Claim("A flight costs $1 (invented).", [])])
    report = check_grounding(itin, {"dest_lisbon"})
    assert not report.ok and report.ungrounded

def test_grounding_catches_fabricated_record_id():
    report = check_claims([Claim("Hotel X costs $50.", ["lod_does_not_exist"])], {"lod_real"})
    assert not report.ok and "lod_does_not_exist" in report.missing_ids

def test_workflow_output_is_grounded_and_fixture_labeled():
    result = run_workflow(TravelPreferences(origin="Nashville", destination="Lisbon", budget_usd=1800, duration_days=4))
    assert result.grounding["ok"]
    bundle = FixtureProvider().get_bundle("dest_lisbon", "Nashville")
    assert set(result.itinerary.citations) <= bundle.all_ids()
    assert result.itinerary.provenance == "fixture"
