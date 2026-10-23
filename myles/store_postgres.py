"""Postgres persistence adapter — SKELETON, UNVERIFIED.

This file exists so the production adapter has a defined home with the
exact same interface as the tested SQLite adapter
(``myles.store.TravelStore`` / ``SQLiteStore``).

It has NOT been run: there is no Postgres server and no ``psycopg``
driver in the offline sandbox, and no database credentials. Every
method raises ``NotImplementedError`` rather than pretending to work.
DDL lives in ``myles/migrations/001_postgres.sql`` (also unverified).

To finish this adapter (future, with a real server available):
  1. ``pip install "psycopg[binary]"`` and set ``DATABASE_URL``.
  2. Apply ``001_postgres.sql``.
  3. Implement each method with the SQL sketched in its docstring,
     using ``%s`` placeholders and JSONB payloads identical to the
     SQLite adapter's JSON columns.
  4. Re-run ``tests/test_store.py`` against this class (parametrize
     the store fixture) — it must pass unchanged.
"""
from __future__ import annotations

import os
from typing import Any

from .schemas import Itinerary, TravelPreferences
from .store import TravelStore

_UNVERIFIED = (
    "PostgresStore is an unverified skeleton — no Postgres server was "
    "available to test it. Use myles.store.SQLiteStore (tested path)."
)


class PostgresStore(TravelStore):
    """Same interface as SQLiteStore; backed by PostgreSQL (future)."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.environ.get("DATABASE_URL", "")

    def _not_implemented(self):
        raise NotImplementedError(_UNVERIFIED)

    def save_preferences(self, user_id: str, prefs: TravelPreferences) -> None:
        # SQL sketch:
        #   INSERT INTO preferences(user_id, prefs_json, updated_at)
        #   VALUES (%s, %s::jsonb, now())
        #   ON CONFLICT (user_id) DO UPDATE
        #     SET prefs_json = EXCLUDED.prefs_json, updated_at = now();
        self._not_implemented()

    def load_preferences(self, user_id: str) -> TravelPreferences | None:
        # SQL sketch: SELECT prefs_json FROM preferences WHERE user_id = %s;
        # Return None when no row (unknown user is not an error).
        self._not_implemented()

    def save_itinerary(
        self,
        user_id: str,
        itinerary: Itinerary | dict[str, Any] | None,
        prefs: TravelPreferences | dict[str, Any] | None = None,
        *,
        ok: bool = True,
        result: Any = None,
    ) -> int:
        # SQL sketch:
        #   INSERT INTO itineraries(user_id, ok, destination_name,
        #     total_cost_usd, itinerary_json, prefs_json, result_json)
        #   VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
        #   RETURNING id;
        self._not_implemented()

    def list_itineraries(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        # SQL sketch:
        #   SELECT ... FROM itineraries WHERE user_id = %s
        #   ORDER BY id DESC LIMIT %s;   -- [] for an unknown user
        self._not_implemented()
