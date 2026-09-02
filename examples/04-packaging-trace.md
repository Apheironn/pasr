# packaging — trace a helper's dependency closure

Repo: [`pypa/packaging`](https://github.com/pypa/packaging) at `929fd4b14`. Reproduce from a clean checkout:

```bash
git clone https://github.com/pypa/packaging && git -C packaging checkout 929fd4b1410ac7ef61ef3f45b2f5d7e87711a9b5 && cd packaging
pasr trace _parse_letter_version src --max-depth 3
```

```text
# _parse_letter_version — 32 definitions, >99% fewer tokens than the index

- src/packaging/_manylinux.py:10  (import NamedTuple)
- src/packaging/_manylinux.py:16  (import Generator)
- src/packaging/_musllinux.py:13  (import NamedTuple)
- src/packaging/_musllinux.py:18  (import Iterator)
- src/packaging/_parser.py:10  (import Sequence)
- src/packaging/_parser.py:11  (import Literal)
- src/packaging/_ranges.py:10-14  (import Any)
- src/packaging/_ranges.py:19  (import Callable)
- src/packaging/_ranges.py:20  (import Union)
- src/packaging/_tokenizer.py:6  (import NoReturn)
- src/packaging/dependency_groups.py:4  (import Mapping)
- src/packaging/direct_url.py:7  (import Any)
- src/packaging/licenses/__init__.py:35  (import NewType)
- src/packaging/licenses/_spdx.py:4  (import TypedDict)
- src/packaging/markers.py:13  (import Callable)
- src/packaging/metadata.py:11-18  (import Any)
- src/packaging/pylock.py:6  (import Mapping)
- src/packaging/pylock.py:9-16  (import Any)
- src/packaging/pylock.py:36  (import Collection)
- src/packaging/ranges.py:24-29  (import Any)
- src/packaging/ranges.py:52  (import Callable)
- src/packaging/requirements.py:6  (import TYPE_CHECKING)
- src/packaging/requirements.py:15  (import Iterator)
- src/packaging/specifiers.py:16-23  (import Any)
- src/packaging/specifiers.py:41  (import Iterable)
- src/packaging/tags.py:15  (import Iterable)
- src/packaging/tags.py:17-21  (import TYPE_CHECKING)
- src/packaging/tags.py:26  (import Callable)
- src/packaging/utils.py:8  (import NewType)
- src/packaging/version.py:15-23  (import Any)
- src/packaging/version.py:52-60  (variable _LETTER_NORMALIZATION)
- src/packaging/version.py:1125-1146  (function _parse_letter_version)
```
