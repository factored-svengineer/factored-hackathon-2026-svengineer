"""Baseline dispute category classifier.

Expected approach: TF-IDF + logistic regression (or keyword rules),
trained/evaluated on complaints.description.
"""

from __future__ import annotations


class BaselineClassifier:
    """Placeholder for TF-IDF + LogisticRegression baseline."""

    def fit(self, texts: list[str], labels: list[str]) -> BaselineClassifier:
        raise NotImplementedError("Train TF-IDF + logistic regression on complaints.description")

    def predict(self, texts: list[str]) -> list[str]:
        raise NotImplementedError("Predict dispute category/subcategory")

    def predict_proba(self, texts: list[str]) -> list[dict[str, float]]:
        raise NotImplementedError("Return per-class probabilities")
