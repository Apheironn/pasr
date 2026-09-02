"""A small ingest pipeline with a clear call chain and several decoys."""

import re

MAX_ROWS = 5000
DEFAULT_ENCODING = "utf-8"


def run_pipeline(path):
    rows = load(path)
    return [normalize(row) for row in rows]


def load(path):
    with open(path, encoding=DEFAULT_ENCODING) as handle:
        raw = handle.read()
    rows = parse(raw)
    return rows[:MAX_ROWS]


def parse(raw):
    chunks = re.split(r"\n+", raw.strip())
    return [chunk.split(",") for chunk in chunks]


def normalize(row):
    return [cell.strip().lower() for cell in row]


# ---- decoys: never reachable from run_pipeline -----------------------------


def legacy_export(rows, destination):
    payload = []
    for row in rows:
        payload.append("|".join(row))
    with open(destination, "w", encoding=DEFAULT_ENCODING) as handle:
        handle.write("\n".join(payload))
    return len(payload)


def deprecated_helper(value, fallback=None):
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    return text


def unrelated_stats(numbers):
    total = sum(numbers)
    count = len(numbers) or 1
    mean = total / count
    variance = sum((n - mean) ** 2 for n in numbers) / count
    return {"total": total, "mean": mean, "variance": variance}
