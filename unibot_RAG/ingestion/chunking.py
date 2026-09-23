import hashlib
import json
import re
from collections.abc import Callable, Iterator
from functools import lru_cache

import numpy as np
import tiktoken
from unibot_RAG.config import Settings
from unibot_RAG.domain import Document, Passage


@lru_cache(maxsize=1)
def tokenizer():
    return tiktoken.get_encoding("cl100k_base")


def token_count(text: str) -> int:
    return len(tokenizer().encode(text, disallowed_special=()))


def token_windows(text: str, size: int, overlap: int) -> Iterator[str]:
    # Character boundaries avoid corrupting UTF-8 when a token bisects a CJK character.
    start = 0
    while start < len(text):
        lo, hi = start + 1, min(len(text), start + size * 16)
        end = start
        while lo <= hi:
            middle = (lo + hi) // 2
            if token_count(text[start:middle]) <= size:
                end, lo = middle, middle + 1
            else:
                hi = middle - 1
        if end == start:
            raise ValueError("Chunk size cannot encode a character")
        yield text[start:end]
        if end == len(text):
            break
        next_start = end
        while (
            next_start > start + 1
            and token_count(text[next_start - 1 : end]) <= overlap
        ):
            next_start -= 1
        start = next_start


def recursive_chunks(text: str, size: int, overlap: int) -> Iterator[str]:
    def units(value, separators):
        if token_count(value) <= size:
            yield value
        elif not separators:
            yield from token_windows(value, size, overlap)
        else:
            for part in re.split(f"(?<={re.escape(separators[0])})", value):
                if part:
                    yield from units(part, separators[1:])

    current = ""
    for part in units(text, ["\n\n", "\n", ". ", "。", " "]):
        if current and token_count(current + part) > size:
            yield current
            current = ""
        current += part
    if current:
        yield current


def chunk_documents(
    documents: list[Document], settings: Settings, embed: Callable | None = None
) -> list[Passage]:
    chunks = []
    for doc in documents:
        if settings.chunk_strategy == "token":
            sections = [(doc.text, "")]
        elif settings.chunk_strategy == "structure":
            sections, heading, lines = [], "", []
            for line in doc.text.splitlines():
                if re.match(r"^#{1,6}\s", line):
                    if lines:
                        sections.append(("\n".join(lines), heading))
                    heading, lines = line, [line]
                else:
                    lines.append(line)
            if lines:
                sections.append(("\n".join(lines), heading))
        elif settings.chunk_strategy == "recursive":
            sections = (
                (part, "")
                for part in recursive_chunks(
                    doc.text, settings.chunk_tokens, settings.chunk_overlap
                )
            )
        else:
            parts = [p for p in re.split(r"\n\s*\n", doc.text) if p.strip()]
            if settings.chunk_strategy == "semantic":
                if embed is None:
                    raise ValueError("Semantic chunking requires an embedding provider")
                # Bound each provider input, including documents with a single huge paragraph.
                segments = []
                for part in parts:
                    for window in token_windows(part, settings.chunk_tokens, 0):
                        segments.append(window)
                        if len(segments) > settings.max_chunks:
                            raise ValueError("Semantic segment limit exceeded")
                parts = segments
                vectors = np.asarray(embed(parts), dtype=float)
                if (
                    vectors.ndim != 2
                    or len(vectors) != len(parts)
                    or not np.isfinite(vectors).all()
                ):
                    raise ValueError("Invalid semantic embeddings")
                groups, current = [], ""
                for i, part in enumerate(parts):
                    similarity = 1.0
                    if i:
                        denom = np.linalg.norm(vectors[i - 1]) * np.linalg.norm(
                            vectors[i]
                        )
                        similarity = (
                            float(np.dot(vectors[i - 1], vectors[i]) / denom)
                            if denom
                            else 0
                        )
                    if current and (
                        similarity < settings.semantic_threshold
                        or token_count(current + "\n\n" + part) > settings.chunk_tokens
                    ):
                        groups.append(current)
                        current = ""
                    current = current + "\n\n" + part if current else part
                if current:
                    groups.append(current)
                parts = groups
            sections = [(p, "") for p in parts]
        for section, heading in sections:
            for text in token_windows(
                section, settings.chunk_tokens, settings.chunk_overlap
            ):
                if not text.strip():
                    continue
                metadata = {
                    **doc.metadata,
                    "heading": heading,
                    "chunk": len(chunks),
                    "strategy": settings.chunk_strategy,
                }
                identity = json.dumps(
                    [doc.source_id, metadata, text], ensure_ascii=False, sort_keys=True
                )
                chunks.append(
                    Passage(
                        id=hashlib.sha256(identity.encode()).hexdigest(),
                        text=text,
                        source_id=doc.source_id,
                        metadata=metadata,
                    )
                )
                if len(chunks) > settings.max_chunks:
                    raise ValueError("Chunk limit exceeded")
    return chunks
