"use client";
import { useState } from "react";
import ItineraryView, { type Itinerary } from "./ItineraryView";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function TripRequestForm() {
  const [origin, setOrigin] = useState("Nashville");
  const [destination, setDestination] = useState("Lisbon");
  const [budget, setBudget] = useState(1800);
  const [days, setDays] = useState(4);
  const [interests, setInterests] = useState("food, history");
  const [result, setResult] = useState<Itinerary | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setError(null); setUnavailable(null); setResult(null);
    try {
      const res = await fetch(`${API}/plan`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ origin, destination: destination || null, budget_usd: budget, duration_days: days,
          interests: interests.split(",").map(s => s.trim()).filter(Boolean) }) });
      const data = await res.json();
      if (data.itinerary) setResult(data.itinerary);
      else if (data.unavailable) setUnavailable(`${data.unavailable.reason} — ${data.unavailable.fallback_message}`);
      else setError((data.errors ?? ["No itinerary could be built within your constraints."]).join("; "));
    } catch { setError("API unreachable. Start the backend (uvicorn myles.api.app:app) and retry — Myles will not invent an itinerary offline."); }
  }
  return (
    <main>
      <h1>Myles — Travel Intelligence Assistant</h1>
      <p>Structured, source-cited itineraries. Fixture data by default; live providers only when configured.</p>
      <form onSubmit={submit}>
        <label>Origin <input value={origin} onChange={e => setOrigin(e.target.value)} required /></label>
        <label>Destination (optional) <input value={destination} onChange={e => setDestination(e.target.value)} /></label>
        <label>Budget (USD) <input type="number" min={1} value={budget} onChange={e => setBudget(+e.target.value)} required /></label>
        <label>Days <input type="number" min={1} max={30} value={days} onChange={e => setDays(+e.target.value)} required /></label>
        <label>Interests (comma-separated) <input value={interests} onChange={e => setInterests(e.target.value)} /></label>
        <button type="submit">Plan trip</button>
      </form>
      {unavailable && <p role="alert">{unavailable}</p>}
      {error && <p role="alert">{error}</p>}
      {result && <ItineraryView itinerary={result} />}
    </main>
  );
}
