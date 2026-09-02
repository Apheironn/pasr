# attrs — "how are class slots built when slots is true"

Repo: [`python-attrs/attrs`](https://github.com/python-attrs/attrs) at `6771a0489`. Reproduce from a clean checkout:

```bash
git clone https://github.com/python-attrs/attrs && git -C attrs checkout 6771a04893780166e4b7826b63599f43ac30d00a && cd attrs
pasr explain "how are class slots built when slots is true" src --budget 3000 --no-write
```

```text
# Selection receipt `ef81baf7078e`

- Query: `how are class slots built when slots is true`
- Sources (29): src/attr/__init__.py, src/attr/__init__.pyi, src/attr/_cmp.py, src/attr/_cmp.pyi, src/attr/_compat.py, src/attr/_config.py, src/attr/_funcs.py, src/attr/_make.py, src/attr/_next_gen.py, src/attr/_typing_compat.pyi, src/attr/_version_info.py, src/attr/_version_info.pyi, src/attr/converters.py, src/attr/converters.pyi, src/attr/exceptions.py, src/attr/exceptions.pyi, src/attr/filters.py, src/attr/filters.pyi, src/attr/setters.py, src/attr/setters.pyi, src/attr/validators.py, src/attr/validators.pyi, src/attrs/__init__.py, src/attrs/__init__.pyi, src/attrs/converters.py, src/attrs/exceptions.py, src/attrs/filters.py, src/attrs/setters.py, src/attrs/validators.py
- Route: **selected**  |  2976/3000 tokens  |  48042 input  |  94% reduction
- Assessment: localized query, confidence 0.663
  - Looks complete for a localized question.

## Kept (15 spans)

| # | provenance | tokens | reasons |
|--:|---|--:|---|
| 1 | `src/attr/__init__.py:1-82` | 396 | active_window |
| 2 | `src/attr/_make.py:86-99` | 134 | symbol |
| 3 | `src/attr/_next_gen.py:485-524` | 400 | bm25, lexical_anchor |
| 4 | `src/attr/validators.py:491-546` | 389 | bm25, lexical_anchor |
| 5 | `src/attr/_version_info.py:1-58` | 393 | bm25, lexical_anchor |
| 6 | `src/attr/_version_info.pyi:1-9` | 57 | bm25, lexical_anchor, symbol |
| 7 | `src/attrs/__init__.pyi:185-231` | 389 | bm25, lexical_anchor |
| 8 | `src/attr/__init__.pyi:250-292` | 395 | bm25, lexical_anchor |
| 9 | `src/attr/exceptions.pyi:1-17` | 125 | bm25, lexical_anchor |
| 10 | `src/attrs/__init__.pyi:232-252` | 196 | active_window |
| 11 | `src/attrs/converters.py:1-3` | 21 | active_window |
| 12 | `src/attrs/exceptions.py:1-3` | 20 | active_window |
| 13 | `src/attrs/filters.py:1-3` | 20 | active_window |
| 14 | `src/attrs/setters.py:1-3` | 21 | active_window |
| 15 | `src/attrs/validators.py:1-3` | 20 | active_window |

## Dropped candidates (56)

skipped: 55 over budget, 1 overlapping, 0 oversized

| provenance | tokens | reasons | rank |
|---|--:|---|--:|
| `src/attr/_make.py:1280-1334` | 391 | bm25, lexical_anchor | 0.0303 |
| `src/attr/_make.py:1898-1945` | 396 | bm25, lexical_anchor | 0.0302 |
| `src/attr/validators.py:659-711` | 342 | bm25, lexical_anchor | 0.0297 |
| `src/attr/validators.py:90-146` | 394 | bm25, lexical_anchor | 0.0294 |
| `src/attr/_next_gen.py:327-380` | 383 | bm25, lexical_anchor | 0.0291 |
| `src/attr/_make.py:1164-1223` | 389 | bm25, lexical_anchor | 0.0283 |
| `src/attr/validators.py:303-369` | 399 | bm25, lexical_anchor | 0.0280 |
| `src/attr/_make.py:1-66` | 384 | bm25, lexical_anchor | 0.0279 |
| `src/attr/validators.py:199-253` | 400 | bm25, lexical_anchor | 0.0278 |
| `src/attr/validators.py:547-604` | 397 | bm25, lexical_anchor | 0.0276 |
| `src/attr/_make.py:1781-1846` | 400 | bm25, lexical_anchor | 0.0273 |
| `src/attr/validators.py:370-428` | 400 | bm25, lexical_anchor | 0.0272 |
| `src/attr/_next_gen.py:219-258` | 389 | bm25, lexical_anchor | 0.0271 |
| `src/attr/_make.py:756-802` | 400 | bm25, lexical_anchor | 0.0270 |
| `src/attr/validators.py:254-302` | 399 | bm25, lexical_anchor | 0.0269 |
| `src/attr/_next_gen.py:1-62` | 398 | bm25, lexical_anchor | 0.0258 |
| `src/attr/_make.py:67-130` | 400 | bm25, lexical_anchor | 0.0257 |
| `src/attr/_make.py:2844-2893` | 400 | bm25, lexical_anchor | 0.0250 |
| `src/attr/_make.py:539-615` | 390 | bm25, lexical_anchor | 0.0244 |
| `src/attr/_make.py:1224-1247` | 393 | bm25, lexical_anchor | 0.0239 |
| `src/attr/exceptions.py:1-73` | 387 | bm25, lexical_anchor | 0.0229 |
| `src/attr/_make.py:803-848` | 393 | bm25, lexical_anchor | 0.0229 |
| `src/attr/_make.py:1065-1113` | 390 | bm25, lexical_anchor | 0.0226 |
| `src/attr/__init__.pyi:74-128` | 393 | bm25, lexical_anchor | 0.0225 |
| `src/attr/_make.py:220-274` | 391 | bm25, lexical_anchor | 0.0219 |
| `src/attr/_next_gen.py:259-291` | 388 | bm25, lexical_anchor | 0.0218 |
| `src/attr/_make.py:616-657` | 397 | bm25, lexical_anchor | 0.0214 |
| `src/attr/_funcs.py:107-184` | 397 | bm25, lexical_anchor | 0.0213 |
| `src/attr/_cmp.py:1-61` | 394 | bm25, lexical_anchor | 0.0211 |
| `src/attr/_funcs.py:185-248` | 395 | bm25, lexical_anchor | 0.0209 |
| `src/attr/_make.py:658-712` | 393 | bm25, lexical_anchor | 0.0208 |
| `src/attr/_make.py:2379-2450` | 393 | bm25, lexical_anchor | 0.0207 |
| `src/attr/_next_gen.py:381-440` | 395 | bm25, lexical_anchor | 0.0205 |
| `src/attr/_make.py:2451-2530` | 397 | bm25, lexical_anchor | 0.0204 |
| `src/attr/_funcs.py:1-54` | 394 | bm25, lexical_anchor | 0.0201 |
| `src/attr/_funcs.py:55-106` | 400 | bm25, lexical_anchor | 0.0201 |
| `src/attr/_funcs.py:321-380` | 397 | bm25, lexical_anchor | 0.0199 |
| `src/attr/_make.py:1383-1443` | 397 | bm25, lexical_anchor | 0.0199 |
| `src/attr/_make.py:2608-2681` | 397 | bm25, lexical_anchor | 0.0196 |
| `src/attr/__init__.pyi:129-168` | 396 | bm25, lexical_anchor | 0.0194 |
| `src/attr/__init__.pyi:331-372` | 395 | bm25, lexical_anchor | 0.0190 |
| `src/attr/_next_gen.py:63-97` | 397 | bm25, lexical_anchor | 0.0185 |
| `src/attr/_make.py:331-384` | 400 | bm25, lexical_anchor | 0.0185 |
| `src/attr/_funcs.py:434-480` | 399 | bm25, lexical_anchor | 0.0184 |
| `src/attr/_next_gen.py:140-176` | 400 | bm25, lexical_anchor | 0.0183 |
| `src/attr/_next_gen.py:177-218` | 398 | bm25, lexical_anchor | 0.0183 |
| `src/attr/_make.py:2956-2960` | 42 | bm25, lexical_anchor | 0.0176 |
| `src/attrs/__init__.pyi:138-184` | 400 | bm25, lexical_anchor | 0.0176 |
| `src/attr/_next_gen.py:617-631` | 102 | bm25, lexical_anchor | 0.0173 |
| `src/attr/_typing_compat.pyi:1-15` | 119 | bm25, lexical_anchor | 0.0173 |
| `src/attr/exceptions.py:74-95` | 131 | bm25, lexical_anchor | 0.0172 |
| `src/attr/converters.py:138-151` | 125 | bm25, lexical_anchor | 0.0171 |
| `src/attr/__init__.pyi:373-388` | 132 | bm25, lexical_anchor | 0.0168 |
| `src/attr/_make.py:682-703` | 156 | symbol | 0.0164 |
| `src/attr/_config.py:1-31` | 216 | bm25, lexical_anchor | 0.0163 |
| `src/attr/_cmp.py:117-160` | 242 | bm25, lexical_anchor | 0.0160 |

```
