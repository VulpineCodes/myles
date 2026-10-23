"""Explainer interface — model reasoning is isolated here.

DeterministicExplainer (default) uses templates + the builder's score
breakdown, so explanations are reproducible and never invent facts.
LLMExplainer is a stub: it requires MODEL_API_KEY and raises if absent.
It is disabled by default and never called in offline tests/evals.
"""
from __future__ import annotations
import os
from abc import ABC, abstractmethod
from .schemas import Itinerary, Tradeoff

class Explainer(ABC):
    @abstractmethod
    def explain(self, itin: Itinerary) -> list[Tradeoff]: ...

class DeterministicExplainer(Explainer):
    def explain(self, itin: Itinerary) -> list[Tradeoff]:
        out = list(itin.tradeoffs)
        b = itin.score_breakdown
        if b:
            out.append(Tradeoff("scoring", f"Score {itin.score:.3f} = cost {b.get('cost_score',0):.2f} + interest {b.get('interest_score',0):.2f} + rating {b.get('rating_score',0):.2f} (weights in builder.py).", itin.score))
        out.append(Tradeoff("provenance", f"All options are '{itin.provenance}' data — verify live prices/availability before booking.", 0.0))
        return out

class LLMExplainer(Explainer):
    """Stub only. Real implementation would call a model API with the
    itinerary's grounded claims as context and validate its output
    against the same grounding checker before returning it."""
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("MODEL_API_KEY", "")
    def explain(self, itin: Itinerary):
        if not self.api_key:
            raise RuntimeError("LLMExplainer disabled: MODEL_API_KEY not set")
        raise NotImplementedError("LLMExplainer is a stub — wire a provider SDK here and ground-check its output")
