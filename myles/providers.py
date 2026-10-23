"""Provider adapter interface + FixtureProvider.

Rule: a provider returns records WITH source identifiers, or it fails
explicitly. It never returns invented data silently. FixtureProvider is
the offline default — every record is labeled provenance='fixture'.
Live providers (future) must implement the same interface and label
their real source.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from .schemas import Destination, FlightOption, LodgingOption, ActivityOption, ProviderBundle

class ProviderError(Exception):
    pass

class TravelProvider(ABC):
    name: str = "base"
    @abstractmethod
    def list_destinations(self) -> list[Destination]: ...
    @abstractmethod
    def get_bundle(self, destination_id: str, origin: str) -> ProviderBundle | None:
        """Return bundle or None if no data. Raise ProviderError on failure."""
    @abstractmethod
    def search(self, origin: str, destination_hint: str | None, interests: list[str]) -> list[ProviderBundle]: ...

class FailingProvider(TravelProvider):
    """For tests / evals: simulates an outage."""
    name = "failing-fixture"
    def list_destinations(self): raise ProviderError("simulated provider outage")
    def get_bundle(self, destination_id, origin): raise ProviderError("simulated provider outage")
    def search(self, origin, destination_hint, interests): raise ProviderError("simulated provider outage")

class EmptyProvider(TravelProvider):
    name = "empty-fixture"
    def list_destinations(self): return []
    def get_bundle(self, destination_id, origin): return None
    def search(self, origin, destination_hint, interests): return []

# --- Fixture catalogue: clearly synthetic, stable ids, realistic ranges ---
_DESTS = [
    Destination("dest_lisbon","Lisbon","Portugal","Coastal capital known for food, history and architecture.",["food","history","architecture","relaxation"]),
    Destination("dest_mexico_city","Mexico City","Mexico","Large capital with museums, food markets and history.",["food","history","art","music"]),
    Destination("dest_kyoto","Kyoto","Japan","Historic temples, gardens and traditional architecture.",["history","architecture","nature","relaxation"]),
    Destination("dest_denver","Denver","USA","Mountain gateway for nature and adventure, family friendly.",["nature","adventure","family"]),
]
_FLIGHTS = [
    FlightOption("flt_lisbon_1","dest_lisbon","Nashville","FixtureAir",620.0,9.5),
    FlightOption("flt_lisbon_2","dest_lisbon","New York","FixtureAir",540.0,7.5),
    FlightOption("flt_mexico_1","dest_mexico_city","Nashville","FixtureAir",380.0,5.0),
    FlightOption("flt_mexico_2","dest_mexico_city","New York","FixtureAir",320.0,4.0),
    FlightOption("flt_kyoto_1","dest_kyoto","Nashville","FixtureAir",980.0,16.0),
    FlightOption("flt_kyoto_2","dest_kyoto","New York","FixtureAir",910.0,14.0),
    FlightOption("flt_denver_1","dest_denver","Nashville","FixtureAir",210.0,3.0),
    FlightOption("flt_denver_2","dest_denver","New York","FixtureAir",260.0,4.5),
]
_LODGING = [
    LodgingOption("lod_lisbon_1","dest_lisbon","Fixture Hotel Alfama",95.0,4.6,["history","relaxation"]),
    LodgingOption("lod_lisbon_2","dest_lisbon","Fixture Budget Baixa",55.0,4.1,["food"]),
    LodgingOption("lod_mexico_1","dest_mexico_city","Fixture Hotel Centro",70.0,4.5,["history","food"]),
    LodgingOption("lod_mexico_2","dest_mexico_city","Fixture Budget Roma",42.0,4.0,["music"]),
    LodgingOption("lod_kyoto_1","dest_kyoto","Fixture Ryokan Gion",140.0,4.8,["history","relaxation"]),
    LodgingOption("lod_kyoto_2","dest_kyoto","Fixture Hotel Arashiyama",85.0,4.3,["nature"]),
    LodgingOption("lod_denver_1","dest_denver","Fixture Mountain Lodge",110.0,4.4,["nature","adventure"]),
    LodgingOption("lod_denver_2","dest_denver","Fixture City Stay",75.0,4.2,["family"]),
]
_ACTIVITIES = [
    ActivityOption("act_lisbon_food","dest_lisbon","Fixture Food Market Tour",45.0,4.7,["food"]),
    ActivityOption("act_lisbon_hist","dest_lisbon","Fixture Old Town Walking Tour",25.0,4.6,["history","architecture"]),
    ActivityOption("act_mexico_food","dest_mexico_city","Fixture Street Food Walk",35.0,4.8,["food"]),
    ActivityOption("act_mexico_museum","dest_mexico_city","Fixture Anthropology Museum Visit",20.0,4.9,["history","art"]),
    ActivityOption("act_kyoto_temple","dest_kyoto","Fixture Temple Circuit",30.0,4.9,["history","architecture"]),
    ActivityOption("act_kyoto_garden","dest_kyoto","Fixture Garden Visit",18.0,4.6,["nature","relaxation"]),
    ActivityOption("act_denver_hike","dest_denver","Fixture Guided Day Hike",60.0,4.7,["nature","adventure"]),
    ActivityOption("act_denver_family","dest_denver","Fixture Science Museum",22.0,4.5,["family"]),
]

class FixtureProvider(TravelProvider):
    name = "fixture"
    def list_destinations(self): return list(_DESTS)
    def get_bundle(self, destination_id, origin):
        dest = next((d for d in _DESTS if d.id == destination_id), None)
        if dest is None: return None
        # Flights are origin-specific when available; otherwise return all for destination
        # (still fixture-labeled) so Nashville/New York both work deterministically.
        flights = [f for f in _FLIGHTS if f.destination_id == destination_id and f.origin == origin]
        if not flights: flights = [f for f in _FLIGHTS if f.destination_id == destination_id]
        return ProviderBundle(dest,
            flights=flights,
            lodging=[l for l in _LODGING if l.destination_id == destination_id],
            activities=[a for a in _ACTIVITIES if a.destination_id == destination_id])
    def search(self, origin, destination_hint, interests):
        bundles = []
        for d in _DESTS:
            if destination_hint and destination_hint.lower() not in d.name.lower() and destination_hint.lower() not in d.id.lower():
                continue
            b = self.get_bundle(d.id, origin)
            if b: bundles.append(b)
        return bundles
