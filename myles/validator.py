"""Constraint validator — hard constraints reject, soft constraints warn."""
from __future__ import annotations
from .schemas import TravelPreferences, Itinerary, ValidationResult, ProviderBundle

def total_cost(bundle: ProviderBundle, flight_id, lodging_id, activity_ids, duration_days, travelers=1) -> float:
    cost = 0.0
    f = next((x for x in bundle.flights if x.id == flight_id), None)
    if f: cost += f.price_usd * travelers
    l = next((x for x in bundle.lodging if x.id == lodging_id), None)
    if l: cost += l.price_per_night_usd * max(duration_days-1, 1)
    for aid in activity_ids:
        a = next((x for x in bundle.activities if x.id == aid), None)
        if a: cost += a.price_usd * travelers
    return round(cost, 2)

def validate_itinerary(prefs: TravelPreferences, itin: Itinerary, bundle: ProviderBundle | None = None) -> ValidationResult:
    hard, soft = [], []
    if itin.total_cost_usd > prefs.budget_usd:
        hard.append(f"total_cost ${itin.total_cost_usd:.2f} exceeds budget ${prefs.budget_usd:.2f}")
    if itin.duration_days != prefs.duration_days:
        hard.append(f"duration {itin.duration_days} != requested {prefs.duration_days}")
    if prefs.max_lodging_per_night_usd and bundle:
        lod = next((x for x in bundle.lodging if x.id == itin.lodging_id), None)
        if lod and lod.price_per_night_usd > prefs.max_lodging_per_night_usd:
            hard.append(f"lodging ${lod.price_per_night_usd}/night exceeds max ${prefs.max_lodging_per_night_usd}")
    # soft: interest match
    ratio = 0.0
    if bundle and prefs.interests:
        tags = set(bundle.destination.tags)
        for a in bundle.activities:
            if a.id in itin.activity_ids: tags |= set(a.tags)
        matched = [i for i in prefs.interests if i in tags]
        ratio = len(matched)/len(prefs.interests) if prefs.interests else 0
        if ratio < 0.5: soft.append(f"low interest match: {ratio:.0%} of interests covered")
    return ValidationResult(ok=len(hard)==0, hard_violations=hard, soft_warnings=soft, interest_match_ratio=ratio)

def validate_bundle_feasibility(prefs: TravelPreferences, bundle: ProviderBundle) -> ValidationResult:
    """Quick feasibility: cheapest possible combination vs budget."""
    if not bundle.flights or not bundle.lodging:
        return ValidationResult(ok=False, hard_violations=["missing flight or lodging options in provider data"])
    cheapest_flight = min(f.price_usd for f in bundle.flights) * prefs.travelers
    cheapest_lodging = min(l.price_per_night_usd for l in bundle.lodging) * max(prefs.duration_days-1,1)
    if cheapest_flight + cheapest_lodging > prefs.budget_usd:
        return ValidationResult(ok=False, hard_violations=[f"cheapest flight+lodging ${cheapest_flight+cheapest_lodging:.2f} exceeds budget ${prefs.budget_usd:.2f}"])
    return ValidationResult(ok=True)
