# pasr-realagent-pilot — 15 tasks

| arm | task_success | tokens_in | context_tokens | round_trips | crit_miss | fallback |
|---|---:|---:|---:|---:|---:|---:|
| broad | 0.467 | 58186 | 58146 | 1.00 | 0.067 | 0.000 |
| native_search | 0.400 | 23051 | 22771 | 6.00 | 0.267 | 0.000 |
| pasr | 0.533 | 5804 | 5764 | 1.00 | 0.133 | 0.000 |
| pasr_fallback | 0.600 | 5804 | 5764 | 1.00 | 0.133 | 0.000 |

## Non-inferiority (vs broad, margin -0.05)

- **pasr**: delta +0.067  CI95 [-0.3333, 0.4667]  point PASS  CI FAIL
- **pasr_fallback**: delta +0.133  CI95 [-0.2, 0.4667]  point PASS  CI FAIL

## Token savings vs broad

- native_search: +60.4%
- pasr: +90.0%
- pasr_fallback: +90.0%
