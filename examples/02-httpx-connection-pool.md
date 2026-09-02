# httpx — "how does the connection pool decide to open a new connection"

Repo: [`encode/httpx`](https://github.com/encode/httpx) at `26d48e063`. Reproduce from a clean checkout:

```bash
git clone https://github.com/encode/httpx && git -C httpx checkout 26d48e0634e6ee9cdc0533996db289ce4b430177 && cd httpx
pasr explain "how does the connection pool decide to open a new connection" httpx --budget 3000 --no-write
```

```text
# Selection receipt `c433fcba5423`

- Query: `how does the connection pool decide to open a new connection`
- Sources (23): httpx/__init__.py, httpx/__version__.py, httpx/_api.py, httpx/_auth.py, httpx/_client.py, httpx/_config.py, httpx/_content.py, httpx/_decoders.py, httpx/_exceptions.py, httpx/_main.py, httpx/_models.py, httpx/_multipart.py, httpx/_status_codes.py, httpx/_transports/__init__.py, httpx/_transports/asgi.py, httpx/_transports/base.py, httpx/_transports/default.py, httpx/_transports/mock.py, httpx/_transports/wsgi.py, httpx/_types.py, httpx/_urlparse.py, httpx/_urls.py, httpx/_utils.py
- Route: **selected**  |  2995/3000 tokens  |  65383 input  |  95% reduction
- Assessment: localized query, confidence 0.544
  - Looks complete for a localized question.

## Kept (17 spans)

| # | provenance | tokens | reasons |
|--:|---|--:|---|
| 1 | `httpx/__init__.py:1-73` | 398 | active_window |
| 2 | `httpx/_urls.py:354-366` | 93 | symbol |
| 3 | `httpx/_client.py:1275-1291` | 125 | symbol |
| 4 | `httpx/_config.py:54-102` | 395 | bm25, lexical_anchor |
| 5 | `httpx/_auth.py:64-128` | 394 | bm25, lexical_anchor |
| 6 | `httpx/_models.py:944-993` | 392 | bm25, lexical_anchor |
| 7 | `httpx/_api.py:1-65` | 398 | bm25, lexical_anchor |
| 8 | `httpx/_status_codes.py:28-33` | 57 | symbol |
| 9 | `httpx/_client.py:760-769` | 85 | symbol |
| 10 | `httpx/_client.py:1474-1483` | 86 | symbol |
| 11 | `httpx/_config.py:132-138` | 47 | symbol |
| 12 | `httpx/_transports/default.py:261-262` | 14 | symbol |
| 13 | `httpx/_utils.py:189-242` | 388 | active_window |
| 14 | `httpx/_exceptions.py:158-161` | 24 | symbol |
| 15 | `httpx/_transports/default.py:39-54` | 65 | symbol |
| 16 | `httpx/_exceptions.py:187-190` | 17 | symbol |
| 17 | `httpx/_exceptions.py:193-196` | 17 | symbol |

## Dropped candidates (41)

skipped: 32 over budget, 9 overlapping, 0 oversized

| provenance | tokens | reasons | rank |
|---|--:|---|--:|
| `httpx/_client.py:1447-1501` | 399 | bm25, lexical_anchor | 0.0318 |
| `httpx/_exceptions.py:152-250` | 397 | bm25, lexical_anchor | 0.0315 |
| `httpx/_config.py:151-201` | 399 | bm25, lexical_anchor | 0.0313 |
| `httpx/_urls.py:283-332` | 397 | bm25, lexical_anchor | 0.0310 |
| `httpx/_client.py:734-790` | 400 | bm25, lexical_anchor | 0.0308 |
| `httpx/_config.py:103-150` | 393 | bm25, lexical_anchor | 0.0288 |
| `httpx/_client.py:439-495` | 393 | bm25, lexical_anchor | 0.0284 |
| `httpx/_client.py:1946-2007` | 397 | bm25, lexical_anchor | 0.0279 |
| `httpx/_client.py:1242-1302` | 399 | bm25, lexical_anchor | 0.0276 |
| `httpx/_client.py:591-631` | 391 | bm25, lexical_anchor | 0.0271 |
| `httpx/_models.py:1045-1100` | 393 | bm25, lexical_anchor | 0.0267 |
| `httpx/_urls.py:333-380` | 395 | bm25, lexical_anchor | 0.0267 |
| `httpx/_urls.py:515-566` | 400 | bm25, lexical_anchor | 0.0262 |
| `httpx/_main.py:194-230` | 395 | bm25, lexical_anchor | 0.0260 |
| `httpx/_urls.py:567-619` | 400 | bm25, lexical_anchor | 0.0258 |
| `httpx/_main.py:57-102` | 395 | bm25, lexical_anchor | 0.0257 |
| `httpx/_main.py:349-420` | 398 | bm25, lexical_anchor | 0.0256 |
| `httpx/_client.py:272-337` | 400 | bm25, lexical_anchor | 0.0253 |
| `httpx/_decoders.py:330-379` | 400 | bm25, lexical_anchor | 0.0252 |
| `httpx/_transports/default.py:1-65` | 399 | bm25, lexical_anchor | 0.0243 |
| `httpx/_client.py:1303-1344` | 400 | bm25, lexical_anchor | 0.0241 |
| `httpx/_config.py:140-147` | 60 | symbol | 0.0154 |
| `httpx/_config.py:149-156` | 89 | symbol | 0.0152 |
| `httpx/_auth.py:113-123` | 96 | symbol | 0.0149 |
| `httpx/_client.py:306-316` | 83 | symbol | 0.0147 |
| `httpx/_client.py:475-492` | 134 | symbol | 0.0145 |
| `httpx/_client.py:1990-2006` | 131 | symbol | 0.0141 |
| `httpx/_exceptions.py:202-205` | 21 | symbol | 0.0135 |
| `httpx/_models.py:961-972` | 90 | symbol | 0.0133 |
| `httpx/_models.py:1065-1076` | 94 | symbol | 0.0132 |
| `httpx/_transports/default.py:217-219` | 32 | symbol | 0.0127 |
| `httpx/_transports/default.py:221-228` | 72 | symbol | 0.0125 |
| `httpx/_transports/default.py:361-363` | 36 | symbol | 0.0122 |
| `httpx/_transports/default.py:365-372` | 76 | symbol | 0.0120 |
| `httpx/_transports/default.py:405-406` | 18 | symbol | 0.0119 |
| `httpx/_urls.py:283-297` | 111 | symbol | 0.0118 |
| `httpx/_urls.py:327-340` | 124 | symbol | 0.0116 |
| `httpx/_urls.py:537-550` | 115 | symbol | 0.0114 |
| `httpx/_urls.py:552-565` | 127 | symbol | 0.0112 |
| `httpx/_urls.py:567-580` | 96 | symbol | 0.0111 |
| `httpx/_urls.py:582-598` | 153 | symbol | 0.0110 |

```
