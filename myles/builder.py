"""Deterministic itinerary builder.

Scoring (explicit, documented, reproducible):
  score = 0.45*cost_score + 0.35*interest_score + 0.20*rating_score
  cost_score     = 1 - (total_cost / budget)   clipped to [0,1], cheaper is better
  interest_score = fraction of user interests matched by destination+chosen activities
  rating_score   = (avg rating of lodging+activities - 3.0) / 2.0 clipped to [0,1]

For each destination bundle we pick the cheapest flight, then try lodging
options in ascending price and greedily add activities (best interest-match
+ rating first) while staying under budget. The best-scoring feasible
bundle wins. If none is feasible, build_itinerary returns None — it does
not relax the budget silently.
"""
from __future__ import annotations
from .schemas import TravelPreferences, Itinerary, Claim, Tradeoff, ProviderBundle
from .validator import validate_itinerary, total_cost

WEIGHTS = {"cost": 0.45, "interest": 0.35, "rating": 0.20}

def _clip(x): return max(0.0, min(1.0, x))

def build_for_bundle(prefs: TravelPreferences, bundle: ProviderBundle) -> Itinerary | None:
    if not bundle.flights or not bundle.lodging: return None
    flight = min(bundle.flights, key=lambda f: f.price_usd)
    nights = max(prefs.duration_days-1, 1)
    # Activities sorted by interest match desc, rating desc, price asc
    def act_key(a):
        match = len(set(a.tags) & set(prefs.interests))
        return (-match, -a.rating, a.price_usd)
    sorted_acts = sorted(bundle.activities, key=act_key)
    best: Itinerary | None = None
    for lodging in sorted(bundle.lodging, key=lambda l: l.price_per_night_usd):
        base = flight.price_usd*prefs.travelers + lodging.price_per_night_usd*nights
        if base > prefs.budget_usd: continue
        chosen, running = [], base
        for a in sorted_acts:
            c = a.price_usd * prefs.travelers
            if running + c <= prefs.budget_usd:
                chosen.append(a); running += c
            if len(chosen) >= 2: break
        total = round(running, 2)
        tags = set(bundle.destination.tags) | {t for a in chosen for t in a.tags}
        interest_score = (len(set(prefs.interests) & tags)/len(prefs.interests)) if prefs.interests else 0
        ratings = [lodging.rating] + [a.rating for a in chosen]
        rating_score = _clip((sum(ratings)/len(ratings)-3.0)/2.0) if ratings else 0
        cost_score = _clip(1 - total/prefs.budget_usd) if prefs.budget_usd else 0
        score = WEIGHTS["cost"]*cost_score + WEIGHTS["interest"]*interest_score + WEIGHTS["rating"]*rating_score
        breakdown = {"cost_score": round(cost_score,4), "interest_score": round(interest_score,4), "rating_score": round(rating_score,4)}
        claims = [
            Claim(f"{bundle.destination.name} is in {bundle.destination.country}.", [bundle.destination.id]),
            Claim(f"Flight {flight.id} via {flight.carrier} costs ${flight.price_usd:.2f} (fixture).", [flight.id]),
            Claim(f"Lodging {lodging.name} costs ${lodging.price_per_night_usd:.2f}/night, rating {lodging.rating} (fixture).", [lodging.id]),
        ] + [Claim(f"Activity {a.name} costs ${a.price_usd:.2f}, rating {a.rating} (fixture).", [a.id]) for a in chosen]
        tradeoffs = [
            Tradeoff("cost", f"Total ${total:.2f} of ${prefs.budget_usd:.2f} budget; cheapest flight and lodging-first search favour cost (weight {WEIGHTS['cost']}).", cost_score),
            Tradeoff("interests", f"Matched {interest_score:.0%} of interests {prefs.interests}.", interest_score),
            Tradeoff("rating", f"Average rating {sum(ratings)/len(ratings):.1f}/5 for lodging+activities.", rating_score),
        ]
        itin = Itinerary(destination_id=bundle.destination.id, destination_name=bundle.destination.name,
            flight_id=flight.id, lodging_id=lodging.id, activity_ids=[a.id for a in chosen],
            duration_days=prefs.duration_days, total_cost_usd=total, score=round(score,4),
            score_breakdown=breakdown, tradeoffs=tradeoffs, claims=claims,
            citations=[bundle.destination.id, flight.id, lodging.id]+[a.id for a in chosen], provenance="fixture")
        v = validate_itinerary(prefs, itin, bundle)
        if not v.ok: continue
        if best is None or itin.score > best.score: best = itin
    return best

def build_itinerary(prefs: TravelPreferences, bundles: list[ProviderBundle]) -> Itinerary | None:
    candidates = [b for b in (build_for_bundle(prefs, bundle) for bundle in bundles) if b is not None]
    if not candidates: return None
    return max(candidates, key=lambda i: i.score)
