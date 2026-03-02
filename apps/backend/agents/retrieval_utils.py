from __future__ import annotations

from typing import Any, Iterable, List


def unique_strings(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def compact_items(values: Iterable[Any], *, limit: int) -> List[str]:
    out: List[str] = []
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def build_anchor_terms(*groups: Iterable[Any], limit: int = 12) -> List[str]:
    merged: List[str] = []
    for group in groups:
        merged.extend(compact_items(group, limit=limit))
    return unique_strings(merged)[:limit]


def evidence_score(*, text: str, citations: list[dict], anchors: Iterable[str]) -> int:
    normalized_text = (text or "").lower()
    score = min(len(citations), 4) * 3
    if len((text or "").strip()) >= 120:
        score += 1
    hits = 0
    for anchor in unique_strings(anchors):
        if anchor.lower() and anchor.lower() in normalized_text:
            hits += 1
    score += min(hits, 4)
    return score


def evidence_is_sufficient(*, score: int, citations: list[dict], text: str) -> bool:
    if len(citations) >= 2:
        return True
    if len(citations) >= 1 and len((text or "").strip()) >= 120:
        return True
    return score >= 6
