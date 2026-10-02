"""Deterministic multilingual lexical/semantic fusion and bounded context allocation."""

import heapq
import math
import re
import unicodedata

STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "what",
        "which",
        "how",
        "do",
        "does",
        "of",
        "for",
        "to",
        "in",
        "on",
        "and",
        "or",
        "my",
        "me",
        "i",
    ]
)


def terms(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    result = set(re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text)) - STOP_WORDS
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        result.update(run[i : i + 2] for i in range(len(run) - 1))
    return result


def lexical_score(query, title, content):
    query_terms = terms(query)
    if not query_terms:
        return 0.0
    title_terms, content_terms = terms(title), terms(content)
    return (2 * len(query_terms & title_terms) + len(query_terms & content_terms)) / (3 * len(query_terms))


def cosine(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    if any(type(n) not in (int, float) or not math.isfinite(n) for n in (*left, *right)):
        return 0.0
    a, b = math.hypot(*left), math.hypot(*right)
    if not a or not b or not math.isfinite(a) or not math.isfinite(b):
        return 0.0
    return sum((x / a) * (y / b) for x, y in zip(left, right))


def rank(rows, query, query_vector, model_key, *, threshold=0.45, max_chars=40000):
    """RRF fuses ranks, never raw lexical and vector scores from different scales."""
    lexical, semantic = [], []
    stats = {"readable_count": 0, "indexed_count": 0}

    def keep(channel, row, score):
        if score <= 0:
            return
        candidate = (score, row.id, row)
        if len(channel) < 100:
            heapq.heappush(channel, candidate)
        elif candidate[:2] > channel[0][:2]:
            heapq.heapreplace(channel, candidate)

    for row in rows:
        stats["readable_count"] += 1
        indexed = (
            bool(row.embedding_vectors)
            and row.embedding_version == row.version
            and row.embedding_model_key == model_key
        )
        stats["indexed_count"] += int(indexed)
        # Oversized references cannot fit even an otherwise empty context.
        if len(f"[personal:{row.kind}:{row.id}@v{row.version}]\n{row.content}") > max_chars:
            continue
        score = lexical_score(query, row.title, row.content)
        keep(lexical, row, score)
        if query_vector and indexed:
            similarity = max(cosine(query_vector, v) for v in row.embedding_vectors)
            if similarity >= threshold:
                keep(semantic, row, similarity)
    fused, candidates = {}, {}
    for channel in (lexical, semantic):
        previous_score, tied_rank = None, 0
        for position, (score, identity, row) in enumerate(
            sorted(channel, key=lambda p: (-p[0], p[1])), start=1
        ):
            if score != previous_score:
                tied_rank, previous_score = position, score
            fused[identity] = fused.get(identity, 0) + 1 / (60 + tied_rank)
            candidates[identity] = row
    semantic_scores = {identity: score for score, identity, _ in semantic}
    lexical_scores = {identity: score for score, identity, _ in lexical}
    # Opposite channel rankings can yield identical RRF sums. Prefer semantic relevance,
    # then lexical relevance; random identifiers are only a final exact-tie fallback.
    return sorted(
        candidates.values(),
        key=lambda r: (
            -fused[r.id],
            -semantic_scores.get(r.id, 0),
            -lexical_scores.get(r.id, 0),
            r.id,
        ),
    ), stats


def allocate(documents, personal, *, limit, max_chars):
    """Inputs are (unique key, complete section) pairs. Never truncate reference bodies."""
    chosen, seen, used = [], set(), 0

    def take(pool, slots, budget):
        nonlocal used
        taken, spent = 0, 0
        for key, section in pool:
            cost = len(section) + (2 if chosen else 0)
            if key in seen or cost > budget - spent or cost > max_chars - used:
                continue
            if taken >= slots or len(chosen) >= limit:
                break
            chosen.append((key, section))
            seen.add(key)
            taken, spent, used = taken + 1, spent + cost, used + cost

    if personal and documents and limit > 1:
        personal_slots = (limit + 2) // 3
        take(personal, personal_slots, max_chars // 3)
        if not chosen:
            # The one-third share is a soft target, never a hard exclusion of a valid reference.
            take(personal, 1, max_chars)
        take(documents, limit - personal_slots, max_chars - used)
    # Spare slots/characters are shared; each round gives both groups a chance.
    while len(chosen) < limit:
        before = len(chosen)
        take(personal, 1, max_chars - used)
        take(documents, 1, max_chars - used)
        if len(chosen) == before:
            break
    return chosen
