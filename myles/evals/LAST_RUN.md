# Myles — Evaluation Harness: Last Run

Cases: **13/13 passed**

## Aggregate metrics

- constraint_satisfaction: **100%**
- structured_output_validity: **100%**
- grounding: **100%**
- tool_selection_success: **100%**
- graceful_failure_handling: **100%**
- cache_behavior: **100%**
- case_pass_rate: **100%**

## Per-case

| Case | Expect | Pass | Destination | Cost | Cache | Provider calls |
|---|---|---|---|---|---|---|
| normal_lisbon_food_history | success | yes | Lisbon | $855.00 | — | — |
| normal_open_destination | success | yes | Mexico City | $519.00 | — | — |
| over_budget_kyoto | unavailable | yes | — | — | — | — |
| impossible_constraints | unavailable | yes | — | — | — | — |
| provider_failure | unavailable | yes | — | — | — | — |
| missing_data_unknown_destination | unavailable | yes | — | — | — | — |
| edge_single_day | success | yes | Denver | $367.00 | — | — |
| edge_leap_date | success | yes | Mexico City | $459.00 | — | — |
| invalid_preferences | error | yes | — | — | — | — |
| empty_provider | unavailable | yes | — | — | — | — |
| cache_repeat_lisbon | success | yes | Lisbon | $855.00 | repeat | 1 |
| cache_repeat_denver | success | yes | Denver | $442.00 | repeat | 1 |
| cache_stale_ttl_zero | success | yes | Lisbon | $855.00 | stale_ttl_zero | 2 |

Cache cases: `repeat` = second identical run served from cache (1 provider call for 2 runs, identical grounded output); `stale_ttl_zero` = TTL=0 forces a fresh provider call on the second run (2 provider calls).

All successful itineraries use fixture-labeled data only. No live prices were queried or fabricated.
