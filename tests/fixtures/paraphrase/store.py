"""A small store with morphologically-named operations."""


def normalize_and_deduplicate_incoming_records(rows):
    seen = set()
    out = []
    for row in rows:
        key = tuple(str(cell).strip().lower() for cell in row)
        if key not in seen:
            seen.add(key)
            out.append(list(key))
    return out


def evict_the_least_recently_used_entry(cache):
    if not cache:
        return None
    oldest = min(cache.items(), key=lambda kv: kv[1]["seen_at"])
    del cache[oldest[0]]
    return oldest[0]


def paginate_results_with_a_stable_cursor(items, cursor, size):
    start = 0 if cursor is None else cursor
    page = items[start : start + size]
    next_cursor = start + size if start + size < len(items) else None
    return page, next_cursor


def retry_a_failing_operation_with_exponential_backoff(operation, attempts):
    delay = 1
    for _ in range(attempts):
        try:
            return operation()
        except Exception:
            delay = min(delay * 2, 60)
    raise RuntimeError("exhausted retries")
