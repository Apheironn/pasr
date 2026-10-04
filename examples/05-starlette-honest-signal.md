# starlette — PASR flags when it is the wrong tool

Repo: [`encode/starlette`](https://github.com/encode/starlette) at `8d0cff820`. Reproduce from a clean checkout:

```bash
git clone https://github.com/encode/starlette && git -C starlette checkout 8d0cff820f89b5d5b19677246293513a9d1c952c && cd starlette
pasr explain "list all the middleware classes provided across the whole package" starlette --budget 3000 --no-write
```

```text
# Selection receipt `52627b7c4a72`

- Query: `list all the middleware classes provided across the whole package`
- Sources (35): starlette/__init__.py, starlette/_compat.py, starlette/_exception_handler.py, starlette/_utils.py, starlette/applications.py, starlette/authentication.py, starlette/background.py, starlette/concurrency.py, starlette/config.py, starlette/convertors.py, starlette/datastructures.py, starlette/endpoints.py, starlette/exceptions.py, starlette/formparsers.py, starlette/middleware/__init__.py, starlette/middleware/authentication.py, starlette/middleware/base.py, starlette/middleware/cors.py, starlette/middleware/errors.py, starlette/middleware/exceptions.py, starlette/middleware/gzip.py, starlette/middleware/httpsredirect.py, starlette/middleware/sessions.py, starlette/middleware/trustedhost.py, starlette/middleware/wsgi.py, starlette/requests.py, starlette/responses.py, starlette/routing.py, starlette/schemas.py, starlette/staticfiles.py, starlette/status.py, starlette/templating.py, starlette/testclient.py, starlette/types.py, starlette/websockets.py
- Route: **selected**  |  2996/3000 tokens  |  55058 input  |  95% reduction
- Assessment: aggregation query, confidence 0.421
  - Aggregation-style question: PASR returns a partial slice and will miss occurrences. Read the files directly or raise budget_tokens.

## Kept (8 spans)

| # | provenance | tokens | reasons |
|--:|---|--:|---|
| 1 | `starlette/staticfiles.py:63-110` | 393 | bm25, lexical_anchor |
| 2 | `starlette/applications.py:1-44` | 398 | bm25, lexical_anchor |
| 3 | `starlette/formparsers.py:153-190` | 395 | bm25, lexical_anchor |
| 4 | `starlette/middleware/base.py:1-44` | 396 | bm25, lexical_anchor |
| 5 | `starlette/routing.py:574-612` | 389 | bm25, lexical_anchor |
| 6 | `starlette/middleware/cors.py:95-139` | 386 | bm25, lexical_anchor |
| 7 | `starlette/middleware/__init__.py:1-42` | 355 | bm25, lexical_anchor |
| 8 | `starlette/templating.py:184-216` | 284 | bm25, lexical_anchor |

## Dropped candidates (56)

skipped: 52 over budget, 4 overlapping, 0 oversized

| provenance | tokens | reasons | rank |
|---|--:|---|--:|
| `starlette/applications.py:76-117` | 378 | bm25, lexical_anchor | 0.0308 |
| `starlette/applications.py:45-75` | 387 | bm25, lexical_anchor | 0.0308 |
| `starlette/applications.py:118-158` | 399 | bm25, lexical_anchor | 0.0296 |
| `starlette/routing.py:374-412` | 399 | bm25, lexical_anchor | 0.0286 |
| `starlette/routing.py:1-53` | 395 | bm25, lexical_anchor | 0.0284 |
| `starlette/routing.py:192-243` | 400 | bm25, lexical_anchor | 0.0282 |
| `starlette/middleware/base.py:45-89` | 391 | bm25, lexical_anchor | 0.0270 |
| `starlette/formparsers.py:236-260` | 230 | bm25, lexical_anchor | 0.0264 |
| `starlette/middleware/errors.py:127-183` | 396 | bm25, lexical_anchor | 0.0257 |
| `starlette/middleware/wsgi.py:1-50` | 400 | bm25, lexical_anchor | 0.0248 |
| `starlette/exceptions.py:58-62` | 50 | bm25, lexical_anchor | 0.0247 |
| `starlette/testclient.py:1-51` | 395 | bm25, lexical_anchor | 0.0243 |
| `starlette/routing.py:285-332` | 384 | bm25, lexical_anchor | 0.0241 |
| `starlette/authentication.py:96-147` | 288 | bm25, lexical_anchor | 0.0238 |
| `starlette/background.py:1-41` | 322 | bm25, lexical_anchor | 0.0233 |
| `starlette/applications.py:204-246` | 392 | bm25, lexical_anchor | 0.0233 |
| `starlette/schemas.py:105-144` | 275 | bm25, lexical_anchor | 0.0231 |
| `starlette/middleware/trustedhost.py:1-51` | 399 | bm25, lexical_anchor | 0.0231 |
| `starlette/middleware/wsgi.py:96-146` | 397 | bm25, lexical_anchor | 0.0227 |
| `starlette/status.py:169-201` | 338 | bm25, lexical_anchor | 0.0227 |
| `starlette/routing.py:413-447` | 399 | bm25, lexical_anchor | 0.0222 |
| `starlette/exceptions.py:1-57` | 398 | bm25, lexical_anchor | 0.0221 |
| `starlette/datastructures.py:501-533` | 393 | bm25, lexical_anchor | 0.0219 |
| `starlette/templating.py:49-99` | 388 | bm25, lexical_anchor | 0.0218 |
| `starlette/formparsers.py:59-108` | 389 | bm25, lexical_anchor | 0.0218 |
| `starlette/datastructures.py:304-344` | 392 | bm25, lexical_anchor | 0.0216 |
| `starlette/datastructures.py:213-261` | 387 | bm25, lexical_anchor | 0.0216 |
| `starlette/routing.py:765-811` | 394 | bm25, lexical_anchor | 0.0214 |
| `starlette/routing.py:613-659` | 398 | bm25, lexical_anchor | 0.0212 |
| `starlette/datastructures.py:534-580` | 391 | bm25, lexical_anchor | 0.0209 |
| `starlette/formparsers.py:1-58` | 386 | bm25, lexical_anchor | 0.0209 |
| `starlette/datastructures.py:262-303` | 396 | bm25, lexical_anchor | 0.0208 |
| `starlette/routing.py:106-147` | 391 | bm25, lexical_anchor | 0.0206 |
| `starlette/formparsers.py:109-152` | 391 | bm25, lexical_anchor | 0.0204 |
| `starlette/datastructures.py:345-392` | 397 | bm25, lexical_anchor | 0.0204 |
| `starlette/testclient.py:255-298` | 393 | bm25, lexical_anchor | 0.0197 |
| `starlette/datastructures.py:446-500` | 397 | bm25, lexical_anchor | 0.0196 |
| `starlette/authentication.py:1-51` | 393 | bm25, lexical_anchor | 0.0195 |
| `starlette/routing.py:448-486` | 394 | bm25, lexical_anchor | 0.0193 |
| `starlette/datastructures.py:581-630` | 400 | bm25, lexical_anchor | 0.0191 |
| `starlette/schemas.py:1-57` | 393 | bm25, lexical_anchor | 0.0190 |
| `starlette/testclient.py:165-204` | 397 | bm25, lexical_anchor | 0.0190 |
| `starlette/applications.py:159-203` | 400 | bm25, lexical_anchor | 0.0188 |
| `starlette/requests.py:255-301` | 396 | bm25, lexical_anchor | 0.0185 |
| `starlette/staticfiles.py:1-62` | 399 | bm25, lexical_anchor | 0.0179 |
| `starlette/responses.py:1-57` | 399 | bm25, lexical_anchor | 0.0179 |
| `starlette/requests.py:205-254` | 400 | bm25, lexical_anchor | 0.0178 |
| `starlette/exceptions.py:61-62` | 29 | symbol | 0.0164 |
| `starlette/staticfiles.py:40-56` | 145 | symbol | 0.0161 |
| `starlette/status.py:200-201` | 30 | symbol | 0.0159 |
| `starlette/applications.py:13` | 11 | symbol | 0.0156 |
| `starlette/applications.py:14` | 10 | symbol | 0.0154 |
| `starlette/applications.py:15` | 10 | symbol | 0.0152 |
| `starlette/applications.py:16` | 9 | symbol | 0.0149 |
| `starlette/applications.py:103-104` | 17 | symbol | 0.0147 |
| `starlette/applications.py:124-132` | 89 | symbol | 0.0145 |

```
