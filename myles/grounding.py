"""Grounding / citation checker.

Every factual claim in an itinerary must reference at least one provider
record id that actually exists in the gathered bundle(s). Claims with no
ids, or ids not in the known set, are flagged as ungrounded. This is the
mechanism that prevents fabricated prices/availability/citations.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from .schemas import Claim, Itinerary

@dataclass
class GroundingReport:
    ok: bool
    total_claims: int = 0
    grounded_claims: int = 0
    ungrounded: list[str] = field(default_factory=list)
    missing_ids: list[str] = field(default_factory=list)
    def to_dict(self):
        return {"ok": self.ok, "total_claims": self.total_claims, "grounded_claims": self.grounded_claims,
                "ungrounded": self.ungrounded, "missing_ids": self.missing_ids}

def check_grounding(itin: Itinerary, known_ids: set[str]) -> GroundingReport:
    ungrounded, missing = [], []
    grounded = 0
    for c in itin.claims:
        if not c.record_ids:
            ungrounded.append(c.text); continue
        bad = [rid for rid in c.record_ids if rid not in known_ids]
        if bad:
            missing.extend(bad); ungrounded.append(c.text)
        else:
            grounded += 1
    # Citations list itself must also resolve
    for cid in itin.citations:
        if cid not in known_ids and cid not in missing:
            missing.append(cid)
    ok = len(ungrounded)==0 and len(missing)==0
    return GroundingReport(ok=ok, total_claims=len(itin.claims), grounded_claims=grounded, ungrounded=ungrounded, missing_ids=missing)

def check_claims(claims: list[Claim], known_ids: set[str]) -> GroundingReport:
    dummy = Itinerary(destination_id="", destination_name="", flight_id=None, lodging_id=None, claims=claims, citations=[])
    return check_grounding(dummy, known_ids)
