import builtins

import pytest

from app.rag.retriever import DisputeRetriever


def test_retriever_ranks_grounded_policy_and_preserves_metadata():
    retriever = DisputeRetriever()
    retriever.index(
        [
            "Policy allows a refund for duplicate card charges.",
            "Transcript confirms the customer reported a stolen card.",
        ],
        [
            {"source": "policy", "document_id": "policy-1"},
            {"source": "transcript", "document_id": "call-1"},
        ],
    )

    results = retriever.retrieve("refund for a duplicate card charge", k=2)

    assert results[0]["metadata"]["source"] == "policy"
    assert "refund" in results[0]["document"].lower()
    assert 0 < results[0]["score"] <= 1


def test_retriever_reindex_replaces_previous_passages():
    retriever = DisputeRetriever()
    retriever.index(["Policy about card refunds"])
    retriever.index(["New policy about wire transfers"])

    results = retriever.retrieve("card refunds")

    assert results == []
    assert retriever.retrieve("wire transfers")[0]["document"] == (
        "New policy about wire transfers"
    )


def test_retriever_validates_metadata_count():
    with pytest.raises(ValueError, match="same number"):
        DisputeRetriever().index(["Policy text"], [])


def test_retriever_works_without_sklearn(monkeypatch):
    original_import = builtins.__import__

    def import_without_sklearn(name, *args, **kwargs):
        if name == "sklearn" or name.startswith("sklearn."):
            raise ImportError("sklearn is unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_sklearn)
    retriever = DisputeRetriever()
    retriever.index(["Policy allows card refunds", "Call about a stolen card"])

    assert retriever.retrieve("refund for card")[0]["document"] == (
        "Policy allows card refunds"
    )