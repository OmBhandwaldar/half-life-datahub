"""Retrieval with an integrity filter.

The point of Half-Life is what recall *refuses* to return. An expired memory is
never handed back, so an agent cannot act on a fact that stopped being true —
it has to re-derive from the catalog instead, which is the correct behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Memory, MemoryStatus
from .store import MemoryStore

#: Words too common to discriminate between memories.
_STOPWORDS = frozenset(
    """a an and are as at be by for from how in is it of on or that the to what
    when where which who why with""".split()
)


@dataclass(frozen=True)
class Recalled:
    memory: Memory
    score: float

    @property
    def warning(self) -> str | None:
        if self.memory.status is MemoryStatus.SUSPECT:
            return (
                f"This memory is SUSPECT (integrity {self.memory.integrity_score}/100): "
                f"{self.memory.invalidation_reason or 'a dependency changed'}. "
                "Verify against the catalog before relying on it."
            )
        return None


class Recall:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def search(
        self,
        query: str,
        limit: int = 5,
        include_suspect: bool = True,
    ) -> list[Recalled]:
        """Return trustworthy memories matching ``query``, best first.

        Matching is done client-side over the memory set rather than through
        the search index: document indexing lags writes by up to 15 minutes,
        and a memory an agent just recorded must be immediately recallable.
        """
        terms = _tokenise(query)
        allowed = {MemoryStatus.VALID}
        if include_suspect:
            allowed.add(MemoryStatus.SUSPECT)

        results = []
        for memory in self._store.list_memories():
            # EXPIRED is never returned, regardless of caller preference.
            if memory.status not in allowed:
                continue
            score = _relevance(memory, terms)
            if score > 0:
                results.append(Recalled(memory=memory, score=score))

        results.sort(key=lambda r: (r.score, r.memory.integrity_score), reverse=True)
        return results[:limit]

    def excluded(self, query: str) -> list[Memory]:
        """Memories withheld because they expired — useful for explaining a gap."""
        terms = _tokenise(query)
        return [
            m
            for m in self._store.list_memories()
            if m.status is MemoryStatus.EXPIRED and _relevance(m, terms) > 0
        ]


def _tokenise(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9_]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _relevance(memory: Memory, terms: set[str]) -> float:
    if not terms:
        return 1.0

    title_terms = _tokenise(memory.title)
    body_terms = _tokenise(memory.text)

    # Title matches count double: a memory's title is its claim.
    hits = 2 * len(terms & title_terms) + len(terms & body_terms)
    if hits == 0:
        return 0.0

    # Weight by integrity so a healthy memory outranks a doubtful one that
    # happens to share more words.
    return hits * (0.5 + memory.integrity_score / 200)
