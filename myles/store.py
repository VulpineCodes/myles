"""Persistence for preferences + itinerary history.

Tested path: ``SQLiteStore`` on the stdlib ``sqlite3`` module — no server,
no extra dependency, and data genuinely survives a process restart /
a new connection to the same file. That is what proves the requirement
"planning context is preserved across interactions/restarts" offline.

Interface: ``TravelStore`` is the contract every adapter implements.
``save_preferences`` / ``load_preferences`` / ``save_itinerary`` /
``save_result`` / ``list_itineraries`` (alias ``list_history``).

Future path — UNVERIFIED, not run in this environment:
``myles/store_postgres.py`` is a skeleton implementing the same
interface against PostgreSQL, with its DDL in
``myles/migrations/001_postgres.sql``. It is labelled unverified
because there is no Postgres server here; do not treat it as tested.
The SQLite adapter and the Postgres skeleton share method names and
JSON payload shapes so swapping adapters does not change callers.

Semantics (both adapters must honour them):
  - Unknown user: ``load_preferences`` -> ``None``,
    ``list_itineraries`` -> ``[]``. Never an exception for "no data".
  - Saving preferences for an existing user overwrites (upsert).
  - Every saved itinerary appends a history row; history is returned
    newest-first unless a caller asks otherwise, and accumulates —
    saving never truncates earlier plans.
"""
from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import Itinerary, TravelPreferences


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prefs_from_dict(d: dict[str, Any]) -> TravelPreferences:
    # Only keep known fields so a stored payload from an older/newer
    # shape still loads instead of raising TypeError.
    known = set(TravelPreferences.__dataclass_fields__)  # type: ignore[attr-defined]
    return TravelPreferences(**{k: v for k, v in d.items() if k in known})


class TravelStore(ABC):
    """Contract for preference / itinerary persistence adapters."""

    @abstractmethod
    def save_preferences(self, user_id: str, prefs: TravelPreferences) -> None: ...

    @abstractmethod
    def load_preferences(self, user_id: str) -> TravelPreferences | None: ...

    @abstractmethod
    def save_itinerary(
        self,
        user_id: str,
        itinerary: Itinerary | dict[str, Any] | None,
        prefs: TravelPreferences | dict[str, Any] | None = None,
        *,
        ok: bool = True,
        result: Any = None,
    ) -> int:
        """Append one history row; return its row id."""

    @abstractmethod
    def list_itineraries(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]: ...

    # --- shared conveniences built on the abstract methods ---------
    def get_preferences(self, user_id: str) -> TravelPreferences | None:
        return self.load_preferences(user_id)

    def list_history(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_itineraries(user_id, limit=limit)

    def get_history(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_itineraries(user_id, limit=limit)

    def save_result(self, user_id: str, result: Any, prefs: TravelPreferences | None = None) -> int:
        """Persist a WorkflowResult (duck-typed to avoid an import cycle)."""
        itinerary = getattr(result, "itinerary", None)
        effective_prefs = prefs
        return self.save_itinerary(
            user_id,
            itinerary,
            prefs=effective_prefs,
            ok=bool(getattr(result, "ok", itinerary is not None)),
            result=result,
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    user_id    TEXT PRIMARY KEY,
    prefs_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS itineraries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    ok               INTEGER NOT NULL DEFAULT 1,
    destination_name TEXT,
    total_cost_usd   REAL,
    itinerary_json   TEXT,
    prefs_json       TEXT,
    result_json      TEXT
);
CREATE INDEX IF NOT EXISTS idx_itineraries_user ON itineraries(user_id, id DESC);
"""


class SQLiteStore(TravelStore):
    """SQLite-backed store. ``path`` may be a file path or ``:memory:``."""

    def __init__(self, path: str | Path = "myles.db") -> None:
        self.path = str(path)
        self._is_memory = self.path == ":memory:"
        self._conn: sqlite3.Connection | None = None
        if self._is_memory:
            self._conn = sqlite3.connect(":memory:")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                conn.commit()
            finally:
                conn.close()

    # -- connection handling ---------------------------------------
    def _connect(self) -> sqlite3.Connection:
        if self._is_memory:
            assert self._conn is not None
            return self._conn
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _run(self, fn):
        if self._is_memory:
            conn = self._connect()
            out = fn(conn)
            conn.commit()
            return out
        conn = self._connect()
        try:
            out = fn(conn)
            conn.commit()
            return out
        finally:
            conn.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- preferences -------------------------------------------------
    def save_preferences(self, user_id: str, prefs: TravelPreferences) -> None:
        payload = json.dumps(prefs.to_dict(), sort_keys=True)

        def _do(conn):
            conn.execute(
                "INSERT INTO preferences(user_id, prefs_json, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET prefs_json=excluded.prefs_json, updated_at=excluded.updated_at",
                (user_id, payload, _utc_now()),
            )

        self._run(_do)

    def load_preferences(self, user_id: str) -> TravelPreferences | None:
        def _do(conn):
            cur = conn.execute("SELECT prefs_json FROM preferences WHERE user_id=?", (user_id,))
            row = cur.fetchone()
            return row[0] if row else None

        raw = self._run(_do)
        if raw is None:
            return None
        return _prefs_from_dict(json.loads(raw))

    # -- itinerary history -------------------------------------------
    def save_itinerary(
        self,
        user_id: str,
        itinerary: Itinerary | dict[str, Any] | None,
        prefs: TravelPreferences | dict[str, Any] | None = None,
        *,
        ok: bool = True,
        result: Any = None,
    ) -> int:
        if itinerary is None:
            itin_dict: dict[str, Any] | None = None
        elif isinstance(itinerary, dict):
            itin_dict = itinerary
        elif hasattr(itinerary, "to_dict"):
            itin_dict = itinerary.to_dict()  # type: ignore[union-attr]
        else:  # pragma: no cover - defensive
            itin_dict = dict(itinerary)  # type: ignore[arg-type]

        if prefs is None:
            prefs_dict = None
        elif isinstance(prefs, dict):
            prefs_dict = prefs
        elif hasattr(prefs, "to_dict"):
            prefs_dict = prefs.to_dict()  # type: ignore[union-attr]
        else:
            prefs_dict = None

        result_dict = None
        if result is not None:
            if hasattr(result, "to_dict"):
                result_dict = result.to_dict()
            elif isinstance(result, dict):
                result_dict = result

        destination = itin_dict.get("destination_name") if itin_dict else None
        total = itin_dict.get("total_cost_usd") if itin_dict else None

        def _do(conn):
            cur = conn.execute(
                "INSERT INTO itineraries(user_id, created_at, ok, destination_name, total_cost_usd, itinerary_json, prefs_json, result_json) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    user_id,
                    _utc_now(),
                    1 if ok else 0,
                    destination,
                    total,
                    json.dumps(itin_dict, sort_keys=True) if itin_dict is not None else None,
                    json.dumps(prefs_dict, sort_keys=True) if prefs_dict is not None else None,
                    json.dumps(result_dict, sort_keys=True, default=str) if result_dict is not None else None,
                ),
            )
            return cur.lastrowid

        return int(self._run(_do))

    def list_itineraries(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        def _do(conn):
            cur = conn.execute(
                "SELECT id, user_id, created_at, ok, destination_name, total_cost_usd, itinerary_json, prefs_json, result_json "
                "FROM itineraries WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, int(limit)),
            )
            rows = cur.fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                # sqlite3.Row in file mode; tuple in :memory: mode (no row_factory there)
                if isinstance(r, sqlite3.Row):
                    vals = dict(r)
                else:
                    vals = {
                        "id": r[0], "user_id": r[1], "created_at": r[2], "ok": r[3],
                        "destination_name": r[4], "total_cost_usd": r[5],
                        "itinerary_json": r[6], "prefs_json": r[7], "result_json": r[8],
                    }
                out.append(
                    {
                        "id": vals["id"],
                        "user_id": vals["user_id"],
                        "created_at": vals["created_at"],
                        "ok": bool(vals["ok"]),
                        "destination_name": vals["destination_name"],
                        "total_cost_usd": vals["total_cost_usd"],
                        "itinerary": json.loads(vals["itinerary_json"]) if vals["itinerary_json"] else None,
                        "prefs": json.loads(vals["prefs_json"]) if vals["prefs_json"] else None,
                        "result": json.loads(vals["result_json"]) if vals["result_json"] else None,
                    }
                )
            return out

        return self._run(_do)
