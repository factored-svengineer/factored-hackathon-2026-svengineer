"""Retrieval over dispute transcripts and policy docs."""

from __future__ import annotations

import math
import re
from typing import Any


class DisputeRetriever:
    """Retrieve relevant passages, using Chroma when it is installed.

    Embeddings are generated locally with TF-IDF, so indexing does not depend
    on downloading a separate embedding model. Without Chroma, cosine search
    runs against the same in-memory vectors.
    """

    def __init__(self, collection_name: str = "dispute_knowledge") -> None:
        self._documents: list[str] = []
        self._metadatas: list[dict[str, Any]] = []
        self._vectors: list[list[float]] = []
        self._vectorizer: Any = None
        self._hashed_idf: list[float] = []
        self._client: Any = None
        self._collection: Any = None
        self._collection_name = collection_name

        try:
            import chromadb
        except ImportError:
            return

        self._client = chromadb.Client()
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def index(self, documents: list[str], metadatas: list[dict] | None = None) -> None:
        if metadatas is not None and len(metadatas) != len(documents):
            raise ValueError("documents and metadatas must contain the same number of items")
        if any(not isinstance(document, str) or not document.strip() for document in documents):
            raise ValueError("Documents must be non-empty strings")

        metadata_items = metadatas if metadatas is not None else [{} for _ in documents]
        vectors: list[list[float]] = []
        vectorizer = None
        self._hashed_idf = []
        if documents:
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer

                vectorizer = TfidfVectorizer(
                    lowercase=True,
                    strip_accents="unicode",
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                )
                vectors = vectorizer.fit_transform(documents).toarray().tolist()
            except ImportError:
                vectors, self._hashed_idf = _hashed_tfidf_vectors(documents)
            except ValueError:
                vectorizer = None
                vectors, self._hashed_idf = _hashed_tfidf_vectors(documents)

        self._documents = list(documents)
        self._metadatas = [dict(metadata) for metadata in metadata_items]
        self._vectors = vectors
        self._vectorizer = vectorizer

        if self._collection is not None:
            self._client.delete_collection(name=self._collection_name)
            self._collection = self._client.create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            if documents:
                ids = [f"passage-{index}" for index in range(len(documents))]
                self._collection.add(ids=ids, documents=documents, embeddings=vectors)

    def retrieve(self, query: str, k: int = 5) -> list[dict]:
        if not isinstance(query, str) or not query.strip() or k <= 0 or not self._documents:
            return []

        if self._vectorizer is not None:
            query_vector = self._vectorizer.transform([query]).toarray()[0].tolist()
        else:
            query_vector = _hashed_tfidf_query_vector(query, self._hashed_idf)

        if self._collection is not None:
            result = self._collection.query(
                query_embeddings=[query_vector],
                n_results=min(k, len(self._documents)),
                include=["distances"],
            )
            ranked = [
                (int(identifier.rsplit("-", 1)[1]), 1.0 - float(distance))
                for identifier, distance in zip(
                    result["ids"][0], result["distances"][0], strict=True
                )
            ]
        else:
            ranked = [
                (index, _dot_product(query_vector, vector))
                for index, vector in enumerate(self._vectors)
            ]
            ranked.sort(key=lambda item: item[1], reverse=True)
            ranked = ranked[:k]

        return [
            {
                "document": self._documents[index],
                "metadata": self._metadatas[index],
                "score": max(0.0, min(1.0, score)),
            }
            for index, score in ranked
            if score > 0
        ]


def _dot_product(left: list[float], right: list[float]) -> float:
    return sum(
        left_value * right_value for left_value, right_value in zip(left, right)
    )


def _hashed_tfidf_vectors(documents: list[str]) -> tuple[list[list[float]], list[float]]:
    features = [_hashed_features(document) for document in documents]
    document_frequency: dict[int, int] = {}
    for item in features:
        for feature in item:
            document_frequency[feature] = document_frequency.get(feature, 0) + 1
    idf_values = [0.0] * 512
    for feature, frequency in document_frequency.items():
        idf_values[feature] = math.log((1 + len(documents)) / (1 + frequency)) + 1
    vectors = [_normalized_vector(item, idf_values) for item in features]
    return vectors, idf_values


def _hashed_tfidf_query_vector(query: str, idf_values: list[float]) -> list[float]:
    return _normalized_vector(_hashed_features(query), idf_values)


def _hashed_features(text: str) -> dict[int, int]:
    import hashlib

    tokens = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
    terms = tokens + [f"{first}_{second}" for first, second in zip(tokens, tokens[1:])]
    counts: dict[int, int] = {}
    for term in terms:
        digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
        feature = int.from_bytes(digest, "big") % 512
        counts[feature] = counts.get(feature, 0) + 1
    return counts


def _normalized_vector(counts: dict[int, int], idf_values: list[float]) -> list[float]:
    vector = [0.0] * 512
    for feature, count in counts.items():
        idf = idf_values[feature] if feature < len(idf_values) else 1.0
        vector[feature] = (1 + math.log(count)) * idf
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector
