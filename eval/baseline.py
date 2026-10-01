"""Baseline dispute-category classifier for held-out evaluation.

TF-IDF + logistic regression (or keyword rules) trained on complaints.description.
"""

from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.pipeline import Pipeline

from eval.metrics import precision_recall_by_label


def train_baseline(texts: list[str], labels: list[str]):
    """Fit TF-IDF + LogisticRegression; return a sklearn Pipeline."""
    _validate_data(texts, labels)
    if len(set(labels)) < 2:
        raise ValueError("Training requires at least two distinct labels")
    model = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    strip_accents="unicode",
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                ),
            ),
            ("classifier", LogisticRegression(max_iter=1000, random_state=42)),
        ]
    )
    return model.fit(texts, labels)


def evaluate_baseline(model, texts: list[str], labels: list[str]) -> dict:
    """Run held-out evaluation and return accuracy + per-class precision/recall."""
    _validate_data(texts, labels)
    predictions = model.predict(texts).tolist()
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "per_class": precision_recall_by_label(labels, predictions),
    }


def _validate_data(texts: list[str], labels: list[str]) -> None:
    if not texts:
        raise ValueError("At least one complaint description is required")
    if len(texts) != len(labels):
        raise ValueError("texts and labels must contain the same number of items")
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("Complaint descriptions must be non-empty strings")
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("Labels must be non-empty strings")
