type Tradeoff = { factor: string; detail: string; score_contribution: number };
export type Itinerary = {
  destination_name: string; total_cost_usd: number; duration_days: number; score: number;
  provenance: string; citations: string[];
  tradeoffs: Tradeoff[];
  claims: { text: string; record_ids: string[] }[];
};

/** Shows the itinerary WITH its trade-offs and source citations — never bare advice. */
export default function ItineraryView({ itinerary }: { itinerary: Itinerary }) {
  return (
    <section aria-label="Itinerary">
      <h2>{itinerary.destination_name} — {itinerary.duration_days} days</h2>
      <p>Total (fixture data): ${itinerary.total_cost_usd.toFixed(2)} · Score: {itinerary.score.toFixed(3)} · Provenance: {itinerary.provenance}</p>
      <h3>Why this plan — trade-offs</h3>
      <ul>{itinerary.tradeoffs.map((t, i) => <li key={i}><strong>{t.factor}:</strong> {t.detail}</li>)}</ul>
      <h3>Sources</h3>
      <ul>{itinerary.claims.map((c, i) => (
        <li key={i}>{c.text} <code>[{c.record_ids.join(", ")}]</code></li>))}
      </ul>
      <p>Record ids cited: {itinerary.citations.join(", ")}. Fixture prices are samples — verify live before booking.</p>
    </section>
  );
}
