"""Retrieval over dispute transcripts and policy docs."""

from __future__ import annotations


class DisputeRetriever:
    """Placeholder for Chroma/FAISS-backed retrieval."""

    def index(self, documents: list[str], metadatas: list[dict] | None = None) -> None:
        raise NotImplementedError("Index transcripts and dispute policies")

    def retrieve(self, query: str, k: int = 5) -> list[dict]:
        raise NotImplementedError("Return top-k grounded passages for the LLM")
