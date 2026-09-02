# starlette — PASR flags when it is the wrong tool

Repo: [`encode/starlette`](https://github.com/encode/starlette) at `8d0cff820`. Reproduce from a clean checkout:

```bash
git clone https://github.com/encode/starlette && git -C starlette checkout 8d0cff820f89b5d5b19677246293513a9d1c952c && cd starlette
pasr explain "list all the middleware classes provided across the whole package" starlette --budget 3000 --no-write
```

```text
# Selection receipt `f91ca52bcbfd`

- Query: `list all the middleware classes provided across the whole package`
- Sources (35): starlette/__init__.py, starlette/_compat.py, starlette/_exception_handler.py, starlette/_utils.py, starlette/applications.py, starlette/authentication.py, starlette/background.py, starlette/concurrency.py, starlette/config.py, starlette/convertors.py, starlette/datastructures.py, starlette/endpoints.py, starlette/exceptions.py, starlette/formparsers.py, starlette/middleware/__init__.py, starlette/middleware/authentication.py, starlette/middleware/base.py, starlette/middleware/cors.py, starlette/middleware/errors.py, starlette/middleware/exceptions.py, starlette/middleware/gzip.py, starlette/middleware/httpsredirect.py, starlette/middleware/sessions.py, starlette/middleware/trustedhost.py, starlette/middleware/wsgi.py, starlette/requests.py, starlette/responses.py, starlette/routing.py, starlette/schemas.py, starlette/staticfiles.py, starlette/status.py, starlette/templating.py, starlette/testclient.py, starlette/types.py, starlette/websockets.py
- Route: **selected**  |  2973/3000 tokens  |  55058 input  |  95% reduction
- Assessment: aggregation query, confidence 0.372
  - Aggregation-style question: PASR returns a partial slice and will miss occurrences. Read the files directly or raise budget_tokens.

## Kept (13 spans)

| # | provenance | tokens | reasons |
|--:|---|--:|---|
| 1 | `starlette/__init__.py:1` | 11 | active_window |
| 2 | `starlette/_compat.py:1-26` | 289 | active_window |
| 3 | `starlette/staticfiles.py:63-110` | 393 | bm25, lexical_anchor |
| 4 | `starlette/applications.py:1-44` | 398 | bm25, lexical_anchor |
| 5 | `starlette/formparsers.py:153-190` | 395 | bm25, lexical_anchor |
| 6 | `starlette/middleware/base.py:1-44` | 396 | bm25, lexical_anchor |
| 7 | `starlette/routing.py:574-612` | 389 | bm25, lexical_anchor |
| 8 | `starlette/templating.py:184-216` | 284 | bm25, lexical_anchor |
| 9 | `starlette/exceptions.py:58-62` | 50 | bm25, lexical_anchor |
| 10 | `starlette/status.py:200-201` | 30 | symbol |
| 11 | `starlette/applications.py:103-104` | 17 | symbol |
| 12 | `starlette/applications.py:124-132` | 89 | symbol |
| 13 | `starlette/websockets.py:177-195` | 232 | active_window |

## Dropped candidates (54)

skipped: 46 over budget, 8 overlapping, 0 oversized

| provenance | tokens | reasons | rank |
|---|--:|---|--:|
| `starlette/applications.py:76-117` | 378 | bm25, lexical_anchor | 0.0310 |
| `starlette/applications.py:45-75` | 387 | bm25, lexical_anchor | 0.0310 |
| `starlette/applications.py:118-158` | 399 | bm25, lexical_anchor | 0.0296 |
| `starlette/routing.py:1-53` | 395 | bm25, lexical_anchor | 0.0287 |
| `starlette/routing.py:374-412` | 399 | bm25, lexical_anchor | 0.0286 |
| `starlette/routing.py:192-243` | 400 | bm25, lexical_anchor | 0.0282 |
| `starlette/formparsers.py:236-260` | 230 | bm25, lexical_anchor | 0.0276 |
| `starlette/middleware/__init__.py:1-42` | 355 | bm25, lexical_anchor | 0.0255 |
| `starlette/middleware/cors.py:95-139` | 386 | bm25, lexical_anchor | 0.0253 |
| `starlette/routing.py:285-332` | 384 | bm25, lexical_anchor | 0.0250 |
| `starlette/authentication.py:96-147` | 288 | bm25, lexical_anchor | 0.0250 |
| `starlette/middleware/base.py:45-89` | 391 | bm25, lexical_anchor | 0.0248 |
| `starlette/testclient.py:1-51` | 395 | bm25, lexical_anchor | 0.0247 |
| `starlette/background.py:1-41` | 322 | bm25, lexical_anchor | 0.0244 |
| `starlette/schemas.py:105-144` | 275 | bm25, lexical_anchor | 0.0243 |
| `starlette/status.py:169-201` | 338 | bm25, lexical_anchor | 0.0237 |
| `starlette/applications.py:204-246` | 392 | bm25, lexical_anchor | 0.0237 |
| `starlette/templating.py:49-99` | 388 | bm25, lexical_anchor | 0.0225 |
| `starlette/formparsers.py:59-108` | 389 | bm25, lexical_anchor | 0.0224 |
| `starlette/datastructures.py:501-533` | 393 | bm25, lexical_anchor | 0.0224 |
| `starlette/datastructures.py:213-261` | 387 | bm25, lexical_anchor | 0.0223 |
| `starlette/exceptions.py:1-57` | 398 | bm25, lexical_anchor | 0.0223 |
| `starlette/routing.py:413-447` | 399 | bm25, lexical_anchor | 0.0222 |
| `starlette/middleware/errors.py:127-183` | 396 | bm25, lexical_anchor | 0.0222 |
| `starlette/datastructures.py:304-344` | 392 | bm25, lexical_anchor | 0.0221 |
| `starlette/routing.py:765-811` | 394 | bm25, lexical_anchor | 0.0218 |
| `starlette/formparsers.py:1-58` | 386 | bm25, lexical_anchor | 0.0218 |
| `starlette/datastructures.py:534-580` | 391 | bm25, lexical_anchor | 0.0216 |
| `starlette/routing.py:613-659` | 398 | bm25, lexical_anchor | 0.0214 |
| `starlette/datastructures.py:262-303` | 396 | bm25, lexical_anchor | 0.0212 |
| `starlette/routing.py:106-147` | 391 | bm25, lexical_anchor | 0.0211 |
| `starlette/formparsers.py:109-152` | 391 | bm25, lexical_anchor | 0.0211 |
| `starlette/datastructures.py:345-392` | 397 | bm25, lexical_anchor | 0.0207 |
| `starlette/middleware/wsgi.py:1-50` | 400 | bm25, lexical_anchor | 0.0205 |
| `starlette/testclient.py:255-298` | 393 | bm25, lexical_anchor | 0.0202 |
| `starlette/authentication.py:1-51` | 393 | bm25, lexical_anchor | 0.0199 |
| `starlette/datastructures.py:446-500` | 397 | bm25, lexical_anchor | 0.0199 |
| `starlette/routing.py:448-486` | 394 | bm25, lexical_anchor | 0.0197 |
| `starlette/schemas.py:1-57` | 393 | bm25, lexical_anchor | 0.0194 |
| `starlette/middleware/trustedhost.py:1-51` | 399 | bm25, lexical_anchor | 0.0192 |
| `starlette/datastructures.py:581-630` | 400 | bm25, lexical_anchor | 0.0192 |
| `starlette/testclient.py:165-204` | 397 | bm25, lexical_anchor | 0.0191 |
| `starlette/middleware/wsgi.py:96-146` | 397 | bm25, lexical_anchor | 0.0190 |
| `starlette/applications.py:159-203` | 400 | bm25, lexical_anchor | 0.0189 |
| `starlette/requests.py:255-301` | 396 | bm25, lexical_anchor | 0.0188 |
| `starlette/staticfiles.py:1-62` | 399 | bm25, lexical_anchor | 0.0180 |
| `starlette/responses.py:1-57` | 399 | bm25, lexical_anchor | 0.0179 |
| `starlette/requests.py:205-254` | 400 | bm25, lexical_anchor | 0.0178 |
| `starlette/exceptions.py:61-62` | 29 | symbol | 0.0164 |
| `starlette/staticfiles.py:40-56` | 145 | symbol | 0.0161 |
| `starlette/applications.py:13` | 11 | symbol | 0.0156 |
| `starlette/applications.py:14` | 10 | symbol | 0.0154 |
| `starlette/applications.py:15` | 10 | symbol | 0.0152 |
| `starlette/applications.py:16` | 9 | symbol | 0.0149 |

```
