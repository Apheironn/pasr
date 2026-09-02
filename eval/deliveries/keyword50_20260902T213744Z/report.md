# pasr-realagent-pilot — 50 tasks

| arm | task_success | tokens_in | context_tokens | round_trips | crit_miss | fallback |
|---|---:|---:|---:|---:|---:|---:|
| broad | 0.660 | 59115 | 59075 | 1.00 | 0.340 | 0.000 |
| native_search | 0.640 | 23181 | 22901 | 6.00 | 0.300 | 0.000 |
| pasr | 0.700 | 5817 | 5777 | 1.00 | 0.080 | 0.000 |
| pasr_fallback | 0.700 | 5895 | 5854 | 1.02 | 0.060 | 0.020 |

## Non-inferiority (vs broad, margin -0.05)

- **pasr**: delta +0.040  CI95 [-0.14, 0.22]  point PASS  CI FAIL
- **pasr_fallback**: delta +0.040  CI95 [-0.14, 0.22]  point PASS  CI FAIL

## Token savings vs broad

- native_search: +60.8%
- pasr: +90.2%
- pasr_fallback: +90.0%
