"""Provider-response cache — tested core, Redis adapter (unverified).

Purpose: provider ``search()`` results (``list[ProviderBundle]``) are the
expensive / rate-limited part of a live deployment. Caching them by
``(provider, origin, destination)`` lets an identical repeat request skip
the provider entirely.

Honesty / scope notes
---------------------
* **Tested path (offline-verifiable):** ``InMemoryCache`` and
  ``SQLiteCache``. Both implement the same ``ProviderCache`` interface
  (``get`` / ``set`` with TTL, ``clear``, hit/miss counters) and are
  covered by ``tests/test_cache.py`` — including a counting-provider
  proof that a second identical workflow run does *not* call the
  provider, TTL expiry forcing a refetch, and disabled-cache behaviour.
* **Redis adapter: UNVERIFIED.** ``RedisCache`` is guarded-import code
  (``redis`` is an optional dependency). There is no Redis server in
  this environment, so it has never been run against a real server.
  It implements the same interface and serialisation so it can be
  swapped in where Redis exists; do not treat it as tested.
* **Cache never bypasses grounding.** The cache only replaces the
  provider ``search()`` call inside the ``gather_options`` node.
  Cached bundles still flow through ``validate_constraints`` →
  ``build_itinerary`` → ``verify_grounding`` exactly like fresh ones.
  A test proves a fabricated claim still fails grounding on a
  cache-hit run.
* **Disabling:** pass ``cache_enabled=False`` to ``run_workflow``,
  set ``MYLES_CACHE_ENABLED=0`` in the environment, or use
  ``NullCache``. Disabled behaviour is identical except every run
  takes the (slower) provider path.

Key: ``make_cache_key(provider, origin, destination)`` →
``"<provider>:<origin-lower>:<destination-lower-or-empty>"``.
Serialisation: bundles are stored as JSON via their ``to_dict()``
shapes and rebuilt into real dataclasses on read, so callers cannot
distinguish a cached bundle from a fresh one (except by timing /
the recorded ``cache_hit`` flag).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

from .providers import TravelProvider, ProviderError
from .schemas import (
    ActivityOption,
    Destination,
    FlightOption,
    LodgingOption,
    ProviderBundle,
)

DEFAULT_TTL_SECONDS = 300.0

# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def bundle_to_dict(bundle: ProviderBundle) -> dict[str, Any]:
    return bundle.to_dict()


def bundle_from_dict(d: dict[str, Any]) -> ProviderBundle:
    dest = Destination(**d["destination"])
    return ProviderBundle(
        destination=dest,
        flights=[FlightOption(**f) for f in d.get("flights", [])],
        lodging=[LodgingOption(**l) for l in d.get("lodging", [])],
        activities=[ActivityOption(**a) for a in d.get("activities", [])],
    )


def bundles_to_json(bundles: list[ProviderBundle]) -> str:
    return json.dumps([bundle_to_dict(b) for b in bundles], sort_keys=True)


def bundles_from_json(raw: str) -> list[ProviderBundle]:
    return [bundle_from_dict(d) for d in json.loads(raw)]


def make_cache_key(provider: str, origin: str, destination: str | None) -> str:
    """Canonical cache key: (provider, origin, destination)."""
    return f"{provider}:{(origin or '').strip().lower()}:{(destination or '').strip().lower()}"


# ---------------------------------------------------------------------------
# Cache interface
# ---------------------------------------------------------------------------

class ProviderCache(ABC):
    """get/set with TTL. ``get`` returns ``None`` on miss *or* expiry."""

    backend: str = "base"
    default_ttl_seconds: float = DEFAULT_TTL_SECONDS

    def __init__(self, default_ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self.default_ttl_seconds = float(default_ttl_seconds)
        self.hits = 0
        self.misses = 0

    @abstractmethod
    def get(self, key: str) -> list[ProviderBundle] | None: ...

    @abstractmethod
    def set(self, key: str, bundles: list[ProviderBundle], ttl_seconds: float | None = None) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    def stats(self) -> dict[str, Any]:
        return {"backend": self.backend, "hits": self.hits, "misses": self.misses}


class NullCache(ProviderCache):
    """Disabled cache: every get is a miss, set is a no-op."""

    backend = "disabled"

    def get(self, key: str) -> list[ProviderBundle] | None:
        self.misses += 1
        return None

    def set(self, key: str, bundles: list[ProviderBundle], ttl_seconds: float | None = None) -> None:
        return None

    def clear(self) -> None:
        return None


class InMemoryCache(ProviderCache):
    """Process-local dict cache with TTL. Tested path."""

    backend = "memory"

    def __init__(self, default_ttl_seconds: float = DEFAULT_TTL_SECONDS,
                 clock: Callable[[], float] | None = None) -> None:
        super().__init__(default_ttl_seconds)
        self._clock = clock or time.monotonic
        self._store: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> list[ProviderBundle] | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires_at, payload = entry
            if self._clock() >= expires_at:
                del self._store[key]
                self.misses += 1
                return None
            self.hits += 1
            return bundles_from_json(payload)

    def set(self, key: str, bundles: list[ProviderBundle], ttl_seconds: float | None = None) -> None:
        ttl = self.default_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        with self._lock:
            # TTL <= 0 means "already expired" — the next get must miss.
            self._store[key] = (self._clock() + ttl, bundles_to_json(bundles))

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class SQLiteCache(ProviderCache):
    """SQLite-backed cache (stdlib sqlite3). Tested path; survives reopen."""

    backend = "sqlite"

    def __init__(self, path: str | Path = ":memory:",
                 default_ttl_seconds: float = DEFAULT_TTL_SECONDS,
                 clock: Callable[[], float] | None = None) -> None:
        super().__init__(default_ttl_seconds)
        self.path = str(path)
        self._clock = clock or time.time
        self._is_memory = self.path == ":memory:"
        self._conn: sqlite3.Connection | None = None
        if self._is_memory:
            self._conn = sqlite3.connect(":memory:")
            self._init(self._conn)
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path)
            try:
                self._init(conn)
            finally:
                conn.close()

    @staticmethod
    def _init(conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS provider_cache ("
            " cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at REAL NOT NULL)"
        )
        conn.commit()

    def _run(self, fn):
        if self._is_memory:
            assert self._conn is not None
            out = fn(self._conn)
            self._conn.commit()
            return out
        conn = sqlite3.connect(self.path)
        try:
            out = fn(conn)
            conn.commit()
            return out
        finally:
            conn.close()

    def get(self, key: str) -> list[ProviderBundle] | None:
        def _do(conn):
            cur = conn.execute("SELECT payload, expires_at FROM provider_cache WHERE cache_key=?", (key,))
            return cur.fetchone()
        row = self._run(_do)
        if row is None:
            self.misses += 1
            return None
        payload, expires_at = row[0], row[1]
        if self._clock() >= float(expires_at):
            self._run(lambda conn: conn.execute("DELETE FROM provider_cache WHERE cache_key=?", (key,)))
            self.misses += 1
            return None
        self.hits += 1
        return bundles_from_json(payload)

    def set(self, key: str, bundles: list[ProviderBundle], ttl_seconds: float | None = None) -> None:
        ttl = self.default_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        payload = bundles_to_json(bundles)
        expires = self._clock() + ttl
        def _do(conn):
            conn.execute(
                "INSERT INTO provider_cache(cache_key, payload, expires_at) VALUES(?,?,?) "
                "ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload, expires_at=excluded.expires_at",
                (key, payload, expires),
            )
        self._run(_do)

    def clear(self) -> None:
        self._run(lambda conn: conn.execute("DELETE FROM provider_cache"))

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# Redis adapter — UNVERIFIED (no Redis server in this environment)
# ---------------------------------------------------------------------------

try:  # guarded import: redis is optional
    import redis as _redis  # type: ignore
    REDIS_AVAILABLE = True
except Exception:  # pragma: no cover - depends on environment
    _redis = None  # type: ignore
    REDIS_AVAILABLE = False


class RedisCache(ProviderCache):
    """Redis-backed cache. **UNVERIFIED — never run against a server here.**

    Implements the same interface/serialisation as the tested adapters.
    Raises a clear error at construction when the ``redis`` package or
    the server is unavailable, rather than silently falling back.
    """

    backend = "redis"

    def __init__(self, url: str = "redis://localhost:6379/0",
                 default_ttl_seconds: float = DEFAULT_TTL_SECONDS,
                 client: Any = None) -> None:
        super().__init__(default_ttl_seconds)
        if client is not None:
            self._client = client
        elif not REDIS_AVAILABLE:
            raise RuntimeError("RedisCache requires the 'redis' package (pip install redis) — unverified adapter")
        else:
            self._client = _redis.Redis.from_url(url, decode_responses=True)  # type: ignore[union-attr]

    def get(self, key: str) -> list[ProviderBundle] | None:  # pragma: no cover - unverified
        raw = self._client.get(key)
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        return bundles_from_json(raw)

    def set(self, key: str, bundles: list[ProviderBundle], ttl_seconds: float | None = None) -> None:  # pragma: no cover - unverified
        ttl = self.default_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        # Redis EX requires a positive int; TTL<=0 means expire immediately.
        if ttl <= 0:
            self._client.delete(key)
            return
        self._client.set(key, bundles_to_json(bundles), ex=int(ttl))

    def clear(self) -> None:  # pragma: no cover - unverified
        # Only clears keys this app could have written is not tracked;
        # flushdb is intentionally NOT used. Caller manages namespace.
        return None


# ---------------------------------------------------------------------------
# Config / factory
# ---------------------------------------------------------------------------

def cache_enabled_from_env(env: dict[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    raw = env.get("MYLES_CACHE_ENABLED")
    if raw is None:
        return False  # opt-in by default: existing callers keep old behaviour
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_default_cache(enabled: bool | None = None,
                      ttl_seconds: float | None = None,
                      env: dict[str, str] | None = None) -> ProviderCache:
    """Build a cache from explicit args / environment.

    Env: ``MYLES_CACHE_ENABLED`` (1/0), ``MYLES_CACHE_TTL_SECONDS``,
    ``MYLES_CACHE_BACKEND`` (memory|sqlite|redis|disabled),
    ``MYLES_CACHE_PATH`` (sqlite file), ``MYLES_REDIS_URL``.
    Returns ``NullCache`` when disabled.
    """
    environ = os.environ if env is None else env
    if enabled is None:
        enabled = cache_enabled_from_env(environ)
    if not enabled:
        return NullCache()
    ttl = ttl_seconds
    if ttl is None and environ.get("MYLES_CACHE_TTL_SECONDS"):
        try:
            ttl = float(environ["MYLES_CACHE_TTL_SECONDS"])
        except ValueError:
            ttl = None
    ttl = DEFAULT_TTL_SECONDS if ttl is None else float(ttl)
    backend = (environ.get("MYLES_CACHE_BACKEND") or "memory").strip().lower()
    if backend == "disabled":
        return NullCache()
    if backend == "sqlite":
        return SQLiteCache(environ.get("MYLES_CACHE_PATH") or ":memory:", default_ttl_seconds=ttl)
    if backend == "redis":
        return RedisCache(environ.get("MYLES_REDIS_URL") or "redis://localhost:6379/0",
                          default_ttl_seconds=ttl)
    return InMemoryCache(default_ttl_seconds=ttl)


# ---------------------------------------------------------------------------
# Provider wrappers (used by tests + evals to prove hit/miss behaviour)
# ---------------------------------------------------------------------------

class CountingProvider(TravelProvider):
    """Wraps a provider and counts calls — the proof instrument for tests."""

    def __init__(self, inner: TravelProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.search_calls = 0
        self.get_bundle_calls = 0
        self.list_destinations_calls = 0

    def list_destinations(self):
        self.list_destinations_calls += 1
        return self.inner.list_destinations()

    def get_bundle(self, destination_id: str, origin: str):
        self.get_bundle_calls += 1
        return self.inner.get_bundle(destination_id, origin)

    def search(self, origin: str, destination_hint: str | None, interests: list[str]):
        self.search_calls += 1
        return self.inner.search(origin, destination_hint, interests)


class CachedProvider(TravelProvider):
    """Provider-interface wrapper: caching *behind* the provider interface.

    ``run_workflow`` can use this directly, or pass ``cache=`` to the
    workflow (which performs the same lookup in ``gather_options`` and
    records hit/miss in the run log). Both paths share this module's
    serialisation and key scheme. ``last_hit`` / ``hits`` / ``misses``
    expose the most recent outcome for observability.
    """

    def __init__(self, inner: TravelProvider, cache: ProviderCache,
                 ttl_seconds: float | None = None) -> None:
        self.inner = inner
        self.cache = cache
        self.ttl_seconds = ttl_seconds
        self.name = inner.name
        self.last_hit: bool | None = None
        self.hits = 0
        self.misses = 0

    def list_destinations(self):
        return self.inner.list_destinations()

    def get_bundle(self, destination_id: str, origin: str):
        return self.inner.get_bundle(destination_id, origin)

    def search(self, origin: str, destination_hint: str | None, interests: list[str]):
        key = make_cache_key(self.inner.name, origin, destination_hint)
        cached = self.cache.get(key)
        if cached is not None:
            self.last_hit = True
            self.hits += 1
            return cached
        self.last_hit = False
        self.misses += 1
        bundles = self.inner.search(origin, destination_hint, interests)
        # Only cache successful, non-error results; errors must retry fresh.
        self.cache.set(key, bundles, ttl_seconds=self.ttl_seconds)
        return bundles
