# requests — "how are redirects resolved and followed"

Repo: [`psf/requests`](https://github.com/psf/requests) at `0e322af87`. Reproduce from a clean checkout:

```bash
git clone https://github.com/psf/requests && git -C requests checkout 0e322af87745eff34caffe4df68456ebc20d9068 && cd requests
pasr explain "how are redirects resolved and followed" src --budget 3000 --no-write
```

```text
# Selection receipt `c9bbe60aa77f`

- Query: `how are redirects resolved and followed`
- Sources (18): src/requests/__init__.py, src/requests/__version__.py, src/requests/_internal_utils.py, src/requests/adapters.py, src/requests/api.py, src/requests/auth.py, src/requests/certs.py, src/requests/compat.py, src/requests/cookies.py, src/requests/exceptions.py, src/requests/help.py, src/requests/hooks.py, src/requests/models.py, src/requests/packages.py, src/requests/sessions.py, src/requests/status_codes.py, src/requests/structures.py, src/requests/utils.py
- Route: **selected**  |  2937/3000 tokens  |  42768 input  |  93% reduction
- Assessment: localized query, confidence 0.743
  - Looks complete for a localized question: the slice covers the query's terms. Answer from it - further retrieval calls are unlikely to add evidence.

## Kept (10 spans)

| # | provenance | tokens | reasons |
|--:|---|--:|---|
| 1 | `src/requests/sessions.py:694-754` | 399 | bm25, lexical_anchor |
| 2 | `src/requests/auth.py:213-260` | 392 | bm25, lexical_anchor |
| 3 | `src/requests/exceptions.py:55-131` | 394 | bm25, lexical_anchor |
| 4 | `src/requests/models.py:981-995` | 83 | symbol |
| 5 | `src/requests/sessions.py:65-116` | 396 | bm25, lexical_anchor |
| 6 | `src/requests/sessions.py:117-159` | 400 | bm25, lexical_anchor |
| 7 | `src/requests/sessions.py:160-212` | 397 | bm25, lexical_anchor |
| 8 | `src/requests/sessions.py:420-463` | 399 | bm25, lexical_anchor |
| 9 | `src/requests/__init__.py:165-176` | 49 | symbol |
| 10 | `src/requests/sessions.py:24-29` | 28 | symbol |

## Dropped candidates (2)

skipped: 0 over budget, 2 overlapping, 0 oversized

| provenance | tokens | reasons | rank |
|---|--:|---|--:|
| `src/requests/exceptions.py:95-96` | 14 | symbol | 0.0164 |
| `src/requests/auth.py:236-239` | 41 | symbol | 0.0159 |

```
