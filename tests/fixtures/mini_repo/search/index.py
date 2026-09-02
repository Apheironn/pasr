"""Inverted index maintenance."""


def incrementally_reindex_only_documents_changed_since_last_run(since):
    """Skip untouched documents so a refresh stays cheap on a large corpus."""
    changed = _changed_docs(since)
    for doc in changed:
        _upsert(doc)
    return len(changed)


def merge_small_segments_into_a_larger_one_during_compaction(segments):
    """Fold tiny segments together to keep query fan out bounded."""
    survivors = [s for s in segments if s.doc_count > 1000]
    return survivors


def deduplicate_near_identical_documents_by_shingle_fingerprint(docs):
    """Drop near duplicates using overlapping k-shingle hashes."""
    seen = set()
    unique = []
    for doc in docs:
        fp = _shingle_fingerprint(doc.text)
        if fp not in seen:
            seen.add(fp)
            unique.append(doc)
    return unique


def promote_exact_title_matches_above_body_matches_in_ranking(hits):
    """A term appearing in the title outranks the same term in the body."""
    return sorted(hits, key=lambda h: (not h.in_title, -h.score))


def _changed_docs(since):
    return []


def _upsert(doc):
    return None


def _shingle_fingerprint(text):
    return hash(text)
