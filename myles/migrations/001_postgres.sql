-- UNVERIFIED — Postgres migration for Myles persistence.
-- Status: skeleton only. There is no Postgres server in the offline
-- sandbox this was written in, so this DDL has NOT been executed or
-- tested against a live server. It mirrors the tested SQLite schema
-- in myles/store.py (same tables / payload shapes) so the future
-- PostgresStore adapter can swap in without changing callers.
-- Run with: psql "$DATABASE_URL" -f myles/migrations/001_postgres.sql

CREATE TABLE IF NOT EXISTS preferences (
    user_id    TEXT PRIMARY KEY,
    prefs_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS itineraries (
    id               BIGSERIAL PRIMARY KEY,
    user_id          TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    ok               BOOLEAN NOT NULL DEFAULT TRUE,
    destination_name TEXT,
    total_cost_usd   DOUBLE PRECISION,
    itinerary_json   JSONB,
    prefs_json       JSONB,
    result_json      JSONB
);

CREATE INDEX IF NOT EXISTS idx_itineraries_user
    ON itineraries(user_id, id DESC);
